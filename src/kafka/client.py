"""
Kafka client wrapper with JSON and AVRO support using confluent-kafka.
Supports SASL/SSL authentication via environment variables.
"""
import json
import logging
import time
from typing import Dict, Any, List, Optional, Union, Set
from confluent_kafka import Producer, Consumer, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka import TopicPartition
from datetime import timedelta
import base64
import io
import threading
import os

try:
    import fastavro
    AVRO_AVAILABLE = True
except ImportError:
    AVRO_AVAILABLE = False

logger = logging.getLogger(__name__)


def get_kafka_config(bootstrap_servers: str = "localhost:9092") -> Dict[str, Any]:
    """
    Build Kafka client configuration including SASL/SSL from environment variables.

    Environment variables:
    - KAFKA_BOOTSTRAP_SERVERS: Kafka bootstrap servers (default: localhost:9092)
    - KAFKA_SECURITY_PROTOCOL: none, plaintext, ssl, sasl_plaintext, sasl_ssl (default: plaintext)
    - KAFKA_SASL_MECHANISM: PLAIN, SCRAM-SHA-256, SCRAM-SHA-512 (if SASL enabled)
    - KAFKA_SASL_USERNAME: SASL username
    - KAFKA_SASL_PASSWORD: SASL password
    - KAFKA_SSL_CA_LOCATION: Path to CA certificate file
    - KAFKA_SSL_CERTIFICATE_LOCATION: Path to client certificate file
    - KAFKA_SSL_KEY_LOCATION: Path to client key file
    - KAFKA_SSL_KEY_PASSWORD: Password for client key
    - KAFKA_CONSUMER_GROUP_PREFIX: Consumer group ID prefix (default: 'wiremock-consumer-')
    - KAFKA_CONSUME_FROM_LATEST: If set to 'true', new consumers start at latest offset instead of earliest (default: false)

    Returns:
        Dictionary of Kafka client configuration
    """
    config = {
        'bootstrap.servers': bootstrap_servers,
        'client.id': 'wiremock-client',
        'api.version.request.timeout.ms': 10000,
        'socket.keepalive.enable': True,
    }

    # Security protocol
    security_protocol = os.getenv("KAFKA_SECURITY_PROTOCOL", "plaintext").lower()
    config['security.protocol'] = security_protocol

    logger.info(f"Using Kafka security protocol: {security_protocol}")

    # SASL configuration
    if security_protocol in ('sasl_plaintext', 'sasl_ssl'):
        sasl_mechanism = os.getenv("KAFKA_SASL_MECHANISM", "PLAIN").upper()
        sasl_username = os.getenv("KAFKA_SASL_USERNAME", "")
        sasl_password = os.getenv("KAFKA_SASL_PASSWORD", "")

        if not sasl_username or not sasl_password:
            logger.warning("SASL enabled but username or password not set")

        config['sasl.mechanism'] = sasl_mechanism
        config['sasl.username'] = sasl_username
        config['sasl.password'] = sasl_password

        logger.info(f"SASL enabled with mechanism: {sasl_mechanism}")

    # SSL configuration
    if security_protocol in ('ssl', 'sasl_ssl'):
        ca_location = os.getenv("KAFKA_SSL_CA_LOCATION", "")
        cert_location = os.getenv("KAFKA_SSL_CERTIFICATE_LOCATION", "")
        key_location = os.getenv("KAFKA_SSL_KEY_LOCATION", "")
        key_password = os.getenv("KAFKA_SSL_KEY_PASSWORD", "")

        if ca_location:
            config['ssl.ca.location'] = ca_location
            logger.info(f"SSL CA certificate: {ca_location}")

        if cert_location:
            config['ssl.certificate.location'] = cert_location

        if key_location:
            config['ssl.key.location'] = key_location

        if key_password:
            config['ssl.key.password'] = key_password

    return config


class KafkaClientWrapper:
    """Wrapper around Kafka producer and consumer with serialization support using confluent-kafka."""

    def __init__(self, bootstrap_servers: str = "localhost:9092"):
        """
        Initialize Kafka client.

        Args:
            bootstrap_servers: Kafka bootstrap servers address
        """
        self.bootstrap_servers = bootstrap_servers
        self.base_config = get_kafka_config(bootstrap_servers)
        self.producer = None
        self.consumers: Dict[str, Consumer] = {}
        self._known_topics: Set[str] = set()  # Cache of verified topics
        self._topics_lock = threading.Lock()
        self._topic_check_interval = 5  # seconds
        self._last_topic_check = {}  # topic -> last check time
        
        # Consumer configuration
        self.consumer_group_prefix = os.getenv("KAFKA_CONSUMER_GROUP_PREFIX", "wiremock-consumer-")
        self.consume_from_latest = os.getenv("KAFKA_CONSUME_FROM_LATEST", "false").lower() == "true"
        
        self._connect_producer()

    def _connect_producer(self) -> None:
        """Create a new Kafka producer with retry logic."""
        max_retries = 5
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                producer_config = self.base_config.copy()
                producer_config.update({
                    'acks': 'all',
                    'retries': 3,  # Max retries for confluent-kafka producer
                    'max.in.flight.requests.per.connection': 1,
                    'request.timeout.ms': 10000,
                    'delivery.timeout.ms': 30000,  # Total time to deliver message
                })
                self.producer = Producer(producer_config)
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
                time_since_check = time.time() - self._last_topic_check[topic]
                if time_since_check < self._topic_check_interval:
                    # Recently checked - return False (cached negative result)
                    # This prevents hammering the broker with repeated checks
                    logger.debug(f"Topic '{topic}' was checked {time_since_check:.1f}s ago, skipping repeated check")
                    return False

            self._last_topic_check[topic] = time.time()

        try:
            admin_config = self.base_config.copy()
            admin_config['socket.timeout.ms'] = 5000  # Short timeout for topic checks
            admin_client = AdminClient(admin_config)

            # List topics with short timeout
            metadata = admin_client.list_topics(timeout=5)
            topics = metadata.topics

            topic_exists = topic in topics
            if topic_exists:
                with self._topics_lock:
                    self._known_topics.add(topic)
                logger.info(f"Topic '{topic}' verified as existing")
            else:
                logger.debug(f"Topic '{topic}' does not exist (not in broker metadata)")

            return topic_exists

        except Exception as e:
            logger.warning(f"Error verifying topic '{topic}': {e}")
            # On error, return False (don't assume topic exists if we can't verify)
            return False

    def produce(self, topic: str, message: Union[str, dict, bytes],
                message_format: str = "auto", schema_id: Optional[int] = None,
                headers: Optional[Dict[str, str]] = None, key: Optional[str] = None) -> Optional[str]:
        """
        Produce a message to a Kafka topic.

        Args:
            topic: Target topic
            message: Message to produce (str, dict, or bytes)
            message_format: Format - "json", "avro", or "auto"
            schema_id: Schema ID for AVRO (optional)
            headers: Optional headers dict to send with message
            key: Optional message key (string or templated value)

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
                for header_key, header_value in headers.items():
                    if isinstance(header_value, str):
                        kafka_headers.append((header_key, header_value.encode('utf-8')))
                    elif isinstance(header_value, bytes):
                        kafka_headers.append((header_key, header_value))
                    else:
                        kafka_headers.append((header_key, str(header_value).encode('utf-8')))

            # Convert key to bytes if provided
            kafka_key = None
            if key:
                if isinstance(key, str):
                    kafka_key = key.encode('utf-8')
                elif isinstance(key, bytes):
                    kafka_key = key
                else:
                    kafka_key = str(key).encode('utf-8')
                logger.debug(f"Producing message to {topic} with key: {key} (encoded: {kafka_key})")

            # Delivery callback for producer
            delivery_event = threading.Event()
            delivery_result = {'err': None, 'msg': None}

            def delivery_callback(err, msg):
                delivery_result['err'] = err
                delivery_result['msg'] = msg
                delivery_event.set()  # Signal that delivery is complete
                if err:
                    logger.warning(f"Failed to produce message to {topic}: {err}")
                else:
                    logger.debug(f"Message produced to {topic} partition {msg.partition()} at offset {msg.offset()}")

            # Send to Kafka
            self.producer.produce(
                topic,
                value=serialized,
                key=kafka_key,
                headers=kafka_headers,
                callback=delivery_callback
            )

            # Flush to ensure message is sent and wait for callback
            self.producer.flush(timeout=10)

            # Check if there was an error
            if delivery_result['err'] is not None:
                logger.warning(f"Producer error: {delivery_result['err']}")
                return None

            # Generate message ID
            message_id = f"{topic}-{int(time.time()*1000)}"
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
                consumer_config = self.base_config.copy()
                consumer_config.update({
                    'group.id': f"{self.consumer_group_prefix}{topic}",
                    'auto.offset.reset': 'latest' if self.consume_from_latest else 'earliest',
                    'enable.auto.commit': True,
                })
                self.consumers[topic] = Consumer(consumer_config)

            consumer = self.consumers[topic]
            consumer.subscribe([topic])

            messages = []
            start_time = time.time()

            while len(messages) < max_messages:
                msg = consumer.poll(timeout=1.0)
                if msg is None:
                    # Timeout reached
                    if time.time() - start_time > timeout_ms / 1000:
                        break
                    continue

                if msg.error():
                    logger.error(f"Consumer error: {msg.error()}")
                    break

                messages.append(self._deserialize_message(msg))
                if len(messages) >= max_messages:
                    break

            logger.info(f"Consumed {len(messages)} messages from {topic}")
            return messages

        except Exception as e:
            logger.error(f"Failed to consume from {topic}: {e}")
            return []

    def consume_latest(self, topic: str, max_messages: int = 10,
                       timeout_ms: int = 500, poll_interval_ms: int = 100,
                       offset_mode: str = "last_N") -> List[Dict[str, Any]]:
        """
        Consume the latest N messages from a Kafka topic, sorted by timestamp (newest first).

        Fetches messages from all partitions, intelligently selecting offsets based on offset_mode,
        and returns the N most recent messages.

        Args:
            topic: Topic to consume from
            max_messages: Maximum number of messages to retrieve (default: 10)
            timeout_ms: Total time budget for polling in milliseconds (default: 500)
            poll_interval_ms: Duration of each individual poll in milliseconds (default: 100)
            offset_mode: How to determine starting offset:
                - "latest": Wait at end for new messages (good for real-time monitoring)
                - "earliest": Start from beginning of topic
                - "last_N": Fetch up to N messages before current end (good for retrieving history)

        Returns:
            List of up to max_messages most recent messages sorted by timestamp (newest first)
        """
        try:
            # Check if topic exists
            if not self._verify_topic_exists(topic):
                logger.warning(f"Topic '{topic}' does not exist.")
                return []

            # Create temporary consumer
            consumer_config = self.base_config.copy()
            # Use configurable group prefix for consistency
            consumer_config.update({
                'group.id': f"{self.consumer_group_prefix}latest-{int(time.time()*1000)}-{id(self)}",
                'enable.auto.commit': False,
                'session.timeout.ms': 6000,
                'fetch.min.bytes': 1,
                'fetch.wait.max.ms': 100,
                'api.version.request.timeout.ms': 5000,
            })
            consumer = Consumer(consumer_config)
            logger.info(f"Created consumer for topic '{topic}' (mode: {offset_mode})")

            try:
                # Get partition metadata
                metadata = consumer.list_topics(topic=topic, timeout=5)
                topic_metadata = metadata.topics.get(topic)

                if not topic_metadata or not topic_metadata.partitions:
                    logger.warning(f"Topic '{topic}' has no partitions")
                    return []

                partitions = list(topic_metadata.partitions.keys())
                logger.info(f"Topic '{topic}' has {len(partitions)} partitions: {sorted(partitions)}")

                # Assign all partitions
                from confluent_kafka import TopicPartition
                topic_partitions = [TopicPartition(topic, p) for p in partitions]
                consumer.assign(topic_partitions)

                # Set starting offset based on mode
                if offset_mode == "earliest":
                    for tp in topic_partitions:
                        tp.offset = 0  # Set offset to beginning
                    consumer.assign(topic_partitions)
                    logger.info("Seeking to beginning (earliest mode)")
                elif offset_mode == "latest":
                    for tp in topic_partitions:
                        tp.offset = -1  # -1 means end in confluent-kafka
                    consumer.assign(topic_partitions)
                    logger.info("Seeking to end (latest mode - wait for new messages)")
                elif offset_mode == "last_N":
                    # Seek to max_messages before the end on each partition
                    for tp in topic_partitions:
                        try:
                            low, high = consumer.get_watermark_offsets(tp, cached=False)
                            start_offset = max(low, high - max_messages)
                            tp.offset = start_offset
                            logger.debug(f"Partition {tp.partition}: seeking to {start_offset} (high={high})")
                        except Exception as e:
                            logger.warning(f"Error getting watermarks for partition {tp.partition}: {e}")
                    consumer.assign(topic_partitions)

                # Poll for messages
                all_messages = []
                start_time = time.time()
                poll_count = 0

                while len(all_messages) < max_messages * 2:  # Fetch more than needed for sorting
                    elapsed_ms = (time.time() - start_time) * 1000
                    if elapsed_ms >= timeout_ms:
                        logger.info(f"Timeout after {poll_count} polls, collected {len(all_messages)} messages")
                        break

                    remaining_ms = timeout_ms - elapsed_ms
                    poll_timeout_s = min(poll_interval_ms, remaining_ms) / 1000.0

                    msg = consumer.poll(timeout=poll_timeout_s)
                    poll_count += 1

                    if msg is None:
                        continue

                    if msg.error():
                        if msg.error().code() == KafkaError._PARTITION_EOF:
                            logger.debug(f"EOF on partition {msg.partition()}")
                            continue
                        else:
                            logger.warning(f"Consumer error: {msg.error()}")
                            continue

                    all_messages.append(self._deserialize_message(msg))

                # Sort by timestamp (newest first) and keep top N
                all_messages.sort(
                    key=lambda m: m.get("timestamp") or 0,
                    reverse=True
                )
                result = all_messages[:max_messages]

                logger.info(f"Consumed {len(result)} messages from {topic} in {elapsed_ms:.0f}ms ({poll_count} polls)")
                return result

            finally:
                consumer.close()

        except Exception as e:
            logger.error(f"Failed to consume latest from {topic}: {e}", exc_info=True)
            return []

    def _deserialize_message(self, kafka_message, topic_type: str = "json") -> dict:
        """
        Deserialize a Kafka message to a dictionary.
        Used by both consume_latest() and consume() methods.

        Args:
            kafka_message: Raw Kafka message from confluent-kafka
            topic_type: Expected format (json, avro, or bytes) - not used in basic version

        Returns:
            Dictionary with message metadata and value
        """
        try:
            # Extract and decode key FIRST before processing value
            # This ensures we capture the key from the Kafka message object
            message_key = None
            try:
                raw_key = kafka_message.key()
                logger.debug(f"kafka_message.key() returned: {raw_key!r} (type: {type(raw_key).__name__})")
                
                if raw_key is not None:
                    if isinstance(raw_key, bytes):
                        message_key = raw_key.decode('utf-8')
                        logger.debug(f"Decoded bytes key to: {message_key}")
                    else:
                        message_key = str(raw_key)
                        logger.debug(f"Converted non-bytes key to string: {message_key}")
                else:
                    logger.debug("kafka_message.key() returned None")
            except Exception as e:
                logger.warning(f"Exception extracting key: {e}", exc_info=True)
                message_key = None
            
            # ...existing code...
            # Try to deserialize as JSON first
            if kafka_message.value():
                try:
                    value = json.loads(kafka_message.value().decode('utf-8'))
                    value_format = "json"
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Try AVRO deserialization
                    if AVRO_AVAILABLE:
                        try:
                            # Check if message has Confluent magic byte (0x0) for schema registry
                            if len(kafka_message.value()) > 5 and kafka_message.value()[0:1] == b'\x00':
                                # Has Confluent schema registry magic byte
                                bytes_reader = io.BytesIO(kafka_message.value()[5:])
                                value = fastavro.reader(bytes_reader).__next__()
                                value_format = "avro"
                            else:
                                # Try raw AVRO without magic byte
                                bytes_reader = io.BytesIO(kafka_message.value())
                                value = fastavro.reader(bytes_reader).__next__()
                                value_format = "avro"
                        except Exception as avro_err:
                            # Fallback to base64
                            logger.debug(f"AVRO deserialization failed: {avro_err}, using base64")
                            value = base64.b64encode(kafka_message.value()).decode('utf-8')
                            value_format = "binary"
                    else:
                        # AVRO not available, use base64
                        value = base64.b64encode(kafka_message.value()).decode('utf-8')
                        value_format = "binary"
            else:
                value = None
                value_format = "null"

            # Process headers
            message_headers = {}
            if kafka_message.headers():
                for key, val in kafka_message.headers():
                    if isinstance(val, bytes):
                        message_headers[key] = val.decode('utf-8')
                    else:
                        message_headers[key] = val

            return {
                "timestamp": kafka_message.timestamp()[1] if kafka_message.timestamp() else None,
                "partition": kafka_message.partition(),
                "offset": kafka_message.offset(),
                "key": message_key,
                "value": value,
                "format": value_format,
                "headers": message_headers,
            }
        except Exception as e:
            logger.error(f"Error deserializing message: {e}", exc_info=True)
            return {
                "error": str(e),
                "value": None,
                "format": "error",
            }

    def close(self) -> None:
        """Close all Kafka connections."""
        if self.producer:
            self.producer.flush()
            self.producer = None
        for consumer in self.consumers.values():
            consumer.close()
        self.consumers.clear()
        logger.info("Kafka connections closed")





