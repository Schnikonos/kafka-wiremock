"""
Kafka client wrapper with JSON and AVRO support.
"""
import json
import logging
import time
from typing import Dict, Any, List, Optional, Union, Set
from kafka import KafkaProducer, KafkaConsumer, KafkaAdminClient
from kafka.errors import KafkaError, TopicAlreadyExistsError
from kafka.admin import NewTopic
from datetime import timedelta
import base64
import io
import threading

try:
    import fastavro
    AVRO_AVAILABLE = True
except ImportError:
    AVRO_AVAILABLE = False

logger = logging.getLogger(__name__)


class KafkaClientWrapper:
    """Wrapper around Kafka producer and consumer with serialization support."""

    def __init__(self, bootstrap_servers: str = "localhost:9092"):
        """
        Initialize Kafka client.

        Args:
            bootstrap_servers: Kafka bootstrap servers address
        """
        self.bootstrap_servers = bootstrap_servers
        self.producer = None
        self.consumers: Dict[str, KafkaConsumer] = {}
        self._known_topics: Set[str] = set()  # Cache of verified topics
        self._topics_lock = threading.Lock()
        self._topic_check_interval = 5  # seconds
        self._last_topic_check = {}  # topic -> last check time
        self._connect_producer()

    def _connect_producer(self) -> None:
        """Create a new Kafka producer with retry logic."""
        max_retries = 5
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                self.producer = KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers,
                    value_serializer=lambda x: self._serialize_value(x),
                    acks='all',
                    retries=3,
                    max_in_flight_requests_per_connection=1,
                )
                logger.info(f"Connected to Kafka at {self.bootstrap_servers}")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Failed to connect to Kafka (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Failed to connect to Kafka after {max_retries} attempts: {e}")
                    raise

    def _verify_topic_exists(self, topic: str) -> bool:
        """
        Verify that a topic exists without creating it.

        Args:
            topic: Topic name to verify

        Returns:
            True if topic exists, False otherwise
        """
        with self._topics_lock:
            # If already verified as existing, use cache
            if topic in self._known_topics:
                return True

            # Rate limit topic checks (don't check same topic too frequently)
            if topic in self._last_topic_check:
                if time.time() - self._last_topic_check[topic] < self._topic_check_interval:
                    return False  # Recently checked and not found

            self._last_topic_check[topic] = time.time()

        try:
            admin_client = KafkaAdminClient(bootstrap_servers=self.bootstrap_servers, request_timeout_ms=5000)
            metadata = admin_client.describe_cluster()

            # Get topic metadata
            topics = admin_client.list_topics()
            admin_client.close()

            topic_exists = topic in topics
            if topic_exists:
                with self._topics_lock:
                    self._known_topics.add(topic)
                logger.debug(f"Topic '{topic}' verified as existing")
            else:
                logger.debug(f"Topic '{topic}' does not exist (not in broker metadata)")

            return topic_exists
        except Exception as e:
            logger.debug(f"Error verifying topic '{topic}': {e}")
            return False

    def produce(self, topic: str, message: Union[str, dict, bytes],
                message_format: str = "auto", schema_id: Optional[int] = None,
                headers: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Produce a message to a Kafka topic.

        Args:
            topic: Target topic
            message: Message to produce (str, dict, or bytes)
            message_format: Format - "json", "avro", or "auto"
            schema_id: Schema ID for AVRO (optional)
            headers: Optional headers dict to send with message

        Returns:
            Message ID or None if failed
        """
        try:
            # Check if topic exists before producing
            if not self._verify_topic_exists(topic):
                logger.warning(f"Topic '{topic}' does not exist. Message not produced (skipping to prevent auto-creation).")
                return None
            
            if not self.producer:
                self._connect_producer()

            # Serialize message
            if isinstance(message, dict):
                serialized = json.dumps(message).encode('utf-8')
            elif isinstance(message, str):
                serialized = message.encode('utf-8')
            elif isinstance(message, bytes):
                serialized = message
            else:
                serialized = str(message).encode('utf-8')

            # Convert headers to proper format if provided
            kafka_headers = None
            if headers:
                kafka_headers = []
                for key, value in headers.items():
                    if isinstance(value, str):
                        kafka_headers.append((key, value.encode('utf-8')))
                    elif isinstance(value, bytes):
                        kafka_headers.append((key, value))
                    else:
                        kafka_headers.append((key, str(value).encode('utf-8')))

            # Send to Kafka
            future = self.producer.send(topic, value=serialized, headers=kafka_headers)
            record_metadata = future.get(timeout=10)

            message_id = f"{record_metadata.topic}-{record_metadata.partition}-{record_metadata.offset}"
            logger.info(f"Produced message to {topic}: {message_id}")

            return message_id
        except Exception as e:
            logger.warning(f"Failed to produce message to topic '{topic}': {e}")
            return None

    def consume(self, topic: str, max_messages: int = 10, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        """
        Consume messages from a Kafka topic.

        Args:
            topic: Topic to consume from
            max_messages: Maximum number of messages to retrieve
            timeout_ms: Consumer timeout in milliseconds

        Returns:
            List of messages with metadata
        """
        try:
            if topic not in self.consumers:
                self.consumers[topic] = KafkaConsumer(
                    topic,
                    bootstrap_servers=self.bootstrap_servers,
                    auto_offset_reset='earliest',
                    consumer_timeout_ms=timeout_ms,
                    group_id=f"wiremock-consumer-{topic}",
                    max_poll_records=max_messages,
                )

            consumer = self.consumers[topic]
            messages = []

            for message in consumer:
                messages.append(self._deserialize_message(message))
                if len(messages) >= max_messages:
                    break

            logger.info(f"Consumed {len(messages)} messages from {topic}")
            return messages

        except Exception as e:
            logger.error(f"Failed to consume from {topic}: {e}")
            return []

    def consume_latest(self, topic: str, max_messages: int = 10,
                       timeout_ms: int = 500, poll_interval_ms: int = 100) -> List[Dict[str, Any]]:
        """
        Consume latest messages from a Kafka topic using a smart polling loop.

        Polls in short intervals and exits early when the consumer has caught up
        (i.e. a poll returns fewer records than requested), avoiding unnecessary
        waiting for hypothetical future messages.

        Args:
            topic: Topic to consume from
            max_messages: Maximum number of messages to retrieve
            timeout_ms: Total time budget for polling in milliseconds (default: 500)
            poll_interval_ms: Duration of each individual poll in milliseconds (default: 100)

        Returns:
            List of messages with metadata
        """
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=self.bootstrap_servers,
                auto_offset_reset='earliest',  # Start from beginning if no offset
                group_id=f"wiremock-consumer-latest-{topic}-{int(time.time())}",  # Unique group ID
                max_poll_records=max_messages,
                enable_auto_commit=False,  # Don't commit offsets
            )

            messages = []
            start_time = time.time()

            while len(messages) < max_messages:
                elapsed_ms = (time.time() - start_time) * 1000
                if elapsed_ms >= timeout_ms:
                    break

                remaining_needed = max_messages - len(messages)
                actual_interval = max(0, min(poll_interval_ms, timeout_ms - elapsed_ms))

                poll_result = consumer.poll(timeout_ms=actual_interval)

                batch_size = 0
                for tp_records in poll_result.values():
                    for record in tp_records:
                        messages.append(self._deserialize_message(record))
                        batch_size += 1
                        if len(messages) >= max_messages:
                            break
                    if len(messages) >= max_messages:
                        break

                # Early exit: fewer records than requested means consumer has caught up
                if batch_size < remaining_needed:
                    break

            consumer.close()
            logger.info(f"Consumed {len(messages)} messages from {topic}")
            return messages

        except Exception as e:
            logger.error(f"Failed to consume latest from {topic}: {e}")
            return []

    def _serialize_value(self, value: Any) -> bytes:
        """Serialize a value for Kafka."""
        if isinstance(value, bytes):
            return value
        elif isinstance(value, str):
            return value.encode('utf-8')
        else:
            return json.dumps(value).encode('utf-8')

    def _deserialize_message(self, kafka_message) -> Dict[str, Any]:
        """Deserialize a Kafka message to a dict."""
        try:
            # Try to deserialize as JSON first
            if kafka_message.value:
                try:
                    value = json.loads(kafka_message.value.decode('utf-8'))
                    value_format = "json"
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Try AVRO deserialization
                    if AVRO_AVAILABLE:
                        try:
                            # Check if message has Confluent magic byte (0x0) for schema registry
                            if len(kafka_message.value) > 5 and kafka_message.value[0:1] == b'\x00':
                                # Has Confluent schema registry magic byte
                                bytes_reader = io.BytesIO(kafka_message.value[5:])
                                value = fastavro.reader(bytes_reader).__next__()
                                value_format = "avro"
                            else:
                                # Try raw AVRO without magic byte
                                bytes_reader = io.BytesIO(kafka_message.value)
                                value = fastavro.reader(bytes_reader).__next__()
                                value_format = "avro"
                        except Exception as avro_err:
                            # Fallback to base64
                            logger.debug(f"AVRO deserialization failed: {avro_err}, using base64")
                            value = base64.b64encode(kafka_message.value).decode('utf-8')
                            value_format = "binary"
                    else:
                        # AVRO not available, use base64
                        value = base64.b64encode(kafka_message.value).decode('utf-8')
                        value_format = "binary"
            else:
                value = None
                value_format = "null"

            return {
                "timestamp": kafka_message.timestamp,
                "partition": kafka_message.partition,
                "offset": kafka_message.offset,
                "key": kafka_message.key.decode('utf-8') if kafka_message.key else None,
                "value": value,
                "format": value_format,
                "headers": {k: v.decode('utf-8') if isinstance(v, bytes) else v
                           for k, v in (kafka_message.headers or [])},
            }
        except Exception as e:
            logger.error(f"Error deserializing message: {e}")
            return {
                "error": str(e),
                "value": None,
                "format": "error",
            }

    def close(self) -> None:
        """Close all Kafka connections."""
        if self.producer:
            self.producer.close()
        for consumer in self.consumers.values():
            consumer.close()
        logger.info("Kafka connections closed")

