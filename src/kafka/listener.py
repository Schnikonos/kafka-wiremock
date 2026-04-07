"""
Kafka listener engine that processes messages and applies rules.
Uses a single consumer with dynamic subscription to monitor all topics.
"""
import json
import logging
import threading
import time
import io
from typing import Dict, List, Set, Optional
from kafka import KafkaConsumer
from kafka.errors import KafkaError

try:
    import fastavro
    AVRO_AVAILABLE = True
except ImportError:
    AVRO_AVAILABLE = False

from ..rules.matcher import MatcherFactory
from ..rules.templater import TemplateRenderer
from ..config.loader import ConfigLoader
from ..config.models import Rule
from .client import KafkaClientWrapper
from .topic_metadata import TopicMetadataManager
from .schema_registry import SchemaRegistry
from ..custom.placeholders import CustomPlaceholderRegistry
from ..fault.injector import FaultInjector

logger = logging.getLogger(__name__)


class KafkaListenerEngine:
    """
    Background listener engine that processes Kafka messages and applies rules.
    Uses a single consumer with dynamic subscription to all configured topics.
    """

    def __init__(self, config_loader: ConfigLoader, kafka_client: KafkaClientWrapper,
                 bootstrap_servers: str = "localhost:9092",
                 custom_placeholder_registry: CustomPlaceholderRegistry = None,
                 message_cache = None,
                 topic_metadata_manager: TopicMetadataManager = None,
                 schema_registry: SchemaRegistry = None):
        """
        Initialize the listener engine.

        Args:
            config_loader: Configuration loader instance
            kafka_client: Kafka client wrapper
            bootstrap_servers: Kafka bootstrap servers
            custom_placeholder_registry: Optional custom placeholder registry
            message_cache: Optional MessageCache instance
            topic_metadata_manager: Optional TopicMetadataManager for dynamic topics
            schema_registry: Optional SchemaRegistry for AVRO decoding
        """
        self.config_loader = config_loader
        self.kafka_client = kafka_client
        self.bootstrap_servers = bootstrap_servers
        self.custom_placeholder_registry = custom_placeholder_registry
        self.message_cache = message_cache
        self.topic_metadata_manager = topic_metadata_manager
        self.schema_registry = schema_registry

        self.consumer: Optional[KafkaConsumer] = None
        self.listener_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._last_subscription_update = 0
        self._matcher_cache = {}
        self.matcher_factory = MatcherFactory()

    def start(self) -> None:
        """Start the listener engine with unified consumer."""
        if self._running:
            logger.warning("Listener engine already running")
            return

        self._running = True

        # Start topic metadata manager if available
        if self.topic_metadata_manager:
            self.topic_metadata_manager.start()

        # Start unified listener thread
        with self._lock:
            self.listener_thread = threading.Thread(
                target=self._unified_listen_loop,
                daemon=True,
                name="kafka-unified-listener"
            )
            self.listener_thread.start()

        logger.info("Kafka listener engine started (unified consumer)")

    def stop(self) -> None:
        """Stop the listener engine."""
        self._running = False

        # Stop topic metadata manager
        if self.topic_metadata_manager:
            self.topic_metadata_manager.stop()

        # Stop listener thread
        if self.listener_thread:
            self.listener_thread.join(timeout=5)

        # Close consumer
        with self._lock:
            if self.consumer:
                try:
                    self.consumer.close()
                except Exception as e:
                    logger.debug(f"Error closing consumer: {e}")
                self.consumer = None

        logger.info("Kafka listener engine stopped")

    def is_listening_to_topic(self, topic: str) -> bool:
        """
        Check if topic is in the unified consumer's subscription.

        Args:
            topic: Topic name to check

        Returns:
            True if consumer is subscribed to topic, False otherwise
        """
        with self._lock:
            if not self.consumer:
                return False
            try:
                subscribed = self.consumer.subscription() or set()
                return topic in subscribed
            except Exception:
                return False

    def ensure_listening_to_topic(self, topic: str, timeout_seconds: int = 5) -> bool:
        """
        Ensure the unified listener is monitoring a specific topic.
        The topic will be added to subscription on next update cycle.

        Args:
            topic: Topic name to listen to
            timeout_seconds: Maximum time to wait for subscription

        Returns:
            True if subscription includes topic within timeout, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            if self.is_listening_to_topic(topic):
                logger.info(f"Listener subscribed to topic: {topic}")
                return True
            time.sleep(0.1)

        logger.warning(f"Timeout waiting for listener subscription to topic: {topic}")
        return False

    def ensure_listening_to_topics(self, topics: List[str], timeout_seconds: int = 5) -> bool:
        """
        Ensure the unified listener is monitoring multiple topics.

        Args:
            topics: List of topic names to listen to
            timeout_seconds: Maximum time to wait per topic

        Returns:
            True if all topics subscribed within timeout, False if any timeout
        """
        all_success = True
        for topic in topics:
            if not self.ensure_listening_to_topic(topic, timeout_seconds):
                all_success = False
        return all_success

    def _unified_listen_loop(self) -> None:
        """
        Unified polling loop for all topics.
        Handles dynamic subscription updates and message processing.
        """
        retry_count = 0
        max_retries = 5

        try:
            while self._running:
                try:
                    # Create consumer on first iteration or after connection loss
                    if self.consumer is None:
                        if retry_count >= max_retries:
                            logger.error(f"Failed to connect to Kafka after {max_retries} retries")
                            time.sleep(5)
                            retry_count = 0
                            continue

                        try:
                            self.consumer = KafkaConsumer(
                                bootstrap_servers=self.bootstrap_servers,
                                auto_offset_reset='latest',
                                group_id='wiremock-listener',
                                enable_auto_commit=True,
                                auto_commit_interval_ms=5000,
                                fetch_max_wait_ms=500,
                                max_poll_records=100
                            )
                            retry_count = 0
                            logger.info("Connected to Kafka consumer")
                            with self._lock:
                                self.consumer = self.consumer
                        except Exception as e:
                            retry_count += 1
                            logger.warning(f"Failed to create consumer (attempt {retry_count}/{max_retries}): {e}")
                            time.sleep(2)
                            continue

                    # Update subscription every 30 seconds
                    current_time = time.time()
                    if current_time - self._last_subscription_update > 30:
                        self._update_subscription()
                        self._last_subscription_update = current_time

                    # Check for config changes
                    if self.config_loader.check_and_reload():
                        logger.debug("Config reloaded, will update topic subscription on next cycle")

                    # Check for custom placeholder changes
                    if self.custom_placeholder_registry and self.custom_placeholder_registry.check_and_reload():
                        logger.info("Custom placeholders reloaded")

                    # Poll for messages
                    messages = self.consumer.poll(timeout_ms=5000)

                    for topic_partition, records in messages.items():
                        topic = topic_partition.topic
                        for message in records:
                            self._process_message(topic, message)

                except Exception as e:
                    logger.error(f"Error in unified listener loop: {e}")
                    with self._lock:
                        if self.consumer:
                            try:
                                self.consumer.close()
                            except:
                                pass
                            self.consumer = None
                    time.sleep(2)

        except Exception as e:
            logger.error(f"Unexpected error in listener thread: {e}")
        finally:
            with self._lock:
                if self.consumer:
                    try:
                        self.consumer.close()
                    except Exception as e:
                        logger.debug(f"Error closing consumer in finally: {e}")
                    self.consumer = None
            logger.info("Unified listener thread stopped")

    def _update_subscription(self) -> None:
        """
        Update consumer subscription based on config and topic existence.
        Only subscribes to topics that exist and are properly configured.
        """
        if not self.consumer:
            return

        try:
            # Get topics from config + metadata
            if self.topic_metadata_manager:
                configured_topics = self.topic_metadata_manager.get_all_topics()
                existing_topics = self.topic_metadata_manager.get_existing_topics()
            else:
                # Fallback: use topics from rules
                configured_topics = set()
                for rule in self.config_loader.get_all_rules():
                    configured_topics.add(rule.input_topic)
                existing_topics = configured_topics

            # Update subscription
            if existing_topics:
                try:
                    self.consumer.subscribe(list(existing_topics))
                    logger.debug(f"Updated consumer subscription to {len(existing_topics)} topics: {sorted(existing_topics)}")
                except Exception as e:
                    logger.error(f"Error updating subscription: {e}")
            else:
                logger.debug("No topics to subscribe to")

        except Exception as e:
            logger.error(f"Error in subscription update: {e}")

    def _process_message(self, topic: str, message) -> None:
        """Process a single message and apply matching rules."""
        try:
            # Deserialize message based on topic type
            topic_type = "json"
            if self.topic_metadata_manager:
                topic_type = self.topic_metadata_manager.get_topic_type(topic)

            message_data, message_format = self._deserialize_message(message, topic_type)

            # Add message to cache with format information
            if self.message_cache:
                try:
                    self.message_cache.add_message(
                        topic=topic,
                        value=message_data,
                        message_format=message_format,
                        timestamp=message.timestamp,
                        partition=message.partition,
                        offset=message.offset,
                        headers=dict(message.headers) if message.headers else None
                    )
                except Exception as e:
                    logger.debug(f"Failed to add message to cache: {e}")

            # Get rules for this topic
            rules = self.config_loader.get_rules_for_topic(topic)

            if not rules:
                logger.debug(f"No rules configured for topic: {topic}")
                return

            # Evaluate rules in priority order
            for rule in rules:
                if self._evaluate_rule(rule, message_data):
                    logger.info(f"Rule matched: {rule.rule_name} for topic {topic}")
                    self._execute_rule(rule, message_data)

                    # Mark message as consumed by rules
                    if self.message_cache:
                        try:
                            self.message_cache.mark_consumed_by_rules(topic, message.offset)
                        except Exception as e:
                            logger.debug(f"Failed to mark message as consumed: {e}")

                    # Stop after first match
                    break

        except Exception as e:
            logger.error(f"Error processing message from {topic}: {e}")

    def _deserialize_message(self, kafka_message, topic_type: str = "json") -> tuple:
        """
        Deserialize a Kafka message based on topic type.

        Args:
            kafka_message: Raw Kafka message
            topic_type: Expected format (json, avro, or bytes)

        Returns:
            Tuple of (message_data, format_type)
        """
        try:
            if not kafka_message.value:
                return None, "null"

            # Try to deserialize based on topic type
            if topic_type == "avro":
                # Try Schema Registry first if available
                if self.schema_registry:
                    message_data, fmt = self.schema_registry.decode(kafka_message.value)
                    if message_data is not None:
                        return message_data, fmt

                # Fallback to raw AVRO deserialization
                if AVRO_AVAILABLE:
                    try:
                        if len(kafka_message.value) > 5 and kafka_message.value[0:1] == b'\x00':
                            bytes_reader = io.BytesIO(kafka_message.value[5:])
                        else:
                            bytes_reader = io.BytesIO(kafka_message.value)
                        message_data = fastavro.reader(bytes_reader).__next__()
                        return message_data, "avro"
                    except Exception as e:
                        logger.debug(f"AVRO fallback deserialization failed: {e}")

                # Fall through to JSON attempt

            elif topic_type == "bytes":
                # Try JSON first, then return as bytes
                try:
                    return json.loads(kafka_message.value.decode('utf-8')), "json"
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return kafka_message.value, "bytes"

            # Default: try JSON
            try:
                return json.loads(kafka_message.value.decode('utf-8')), "json"
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Try AVRO as fallback
                if AVRO_AVAILABLE:
                    try:
                        if len(kafka_message.value) > 5 and kafka_message.value[0:1] == b'\x00':
                            bytes_reader = io.BytesIO(kafka_message.value[5:])
                        else:
                            bytes_reader = io.BytesIO(kafka_message.value)
                        message_data = fastavro.reader(bytes_reader).__next__()
                        return message_data, "avro"
                    except Exception:
                        pass

                # Last resort: return bytes as-is
                return kafka_message.value, "bytes"

        except Exception as e:
            logger.error(f"Error deserializing message: {e}")
            return None, "error"

    def _evaluate_rule(self, rule: Rule, message_data: any) -> bool:
        """Evaluate if a message matches a rule."""
        try:
            # If no conditions, rule matches everything (wildcard)
            if not rule.conditions:
                return True

            # All conditions must match (AND logic)
            for condition in rule.conditions:
                matcher = MatcherFactory.create(condition.type)

                # Build condition based on type
                if condition.type == 'jsonpath':
                    match_condition = {
                        'path': condition.expression,
                        'value': condition.value,
                        'regex': condition.regex
                    }
                else:
                    # For other matchers, use the value or regex
                    match_condition = condition.regex if condition.regex else condition.value

                result = matcher.match(message_data, match_condition)
                if not result.matched:
                    return False

            return True

        except Exception as e:
            logger.warning(f"Error evaluating rule {rule.rule_name}: {e}")
            return False

    def _execute_rule(self, rule: Rule, message_data: any) -> None:
        """Execute a rule by producing output messages."""
        try:
            # Check if rule is skipped
            if rule.skip:
                logger.debug(f"Rule {rule.rule_name} is skipped, not executing")
                return

            # Get matcher and match result to get context
            matcher_contexts = {}
            for condition in rule.conditions:
                matcher = MatcherFactory.create(condition.type)

                # Build condition based on type
                if condition.type == 'jsonpath':
                    match_condition = {
                        'path': condition.expression,
                        'value': condition.value,
                        'regex': condition.regex
                    }
                else:
                    match_condition = condition.regex if condition.regex else condition.value

                match_result = matcher.match(message_data, match_condition)
                matcher_contexts.update(match_result.context)

            # Build initial context from message data - add all accessors
            if isinstance(message_data, dict):
                matcher_contexts['message'] = message_data
                matcher_contexts['$'] = message_data

                # Add each field with multiple accessors for flexibility
                for key, value in message_data.items():
                    # Direct access: amount, orderId
                    matcher_contexts[key] = value
                    # JSONPath style without dot: $.amount, $.orderId
                    matcher_contexts[f'$.{key}'] = value
                    # Also add with .get() compatible format
                    if isinstance(value, dict):
                        # For nested objects, add the full path
                        for nested_key, nested_value in value.items():
                            matcher_contexts[f'{key}.{nested_key}'] = nested_value
                            matcher_contexts[f'$.{key}.{nested_key}'] = nested_value

            logger.debug(f"Context before custom placeholders: {list(matcher_contexts.keys())}")
            logger.debug(f"Context values: {matcher_contexts}")

            # Execute custom placeholder pipeline if available
            if self.custom_placeholder_registry:
                try:
                    matcher_contexts = self.custom_placeholder_registry.execute_pipeline(matcher_contexts)
                    logger.debug(f"Custom placeholder pipeline executed. Context now has: {list(matcher_contexts.keys())}")
                except Exception as e:
                    logger.error(f"Error executing custom placeholder pipeline: {e}")
                    # Continue without custom placeholders

            # Render and produce output messages
            for output in rule.outputs:
                try:
                    # Apply delay if specified
                    if output.delay_ms and output.delay_ms > 0:
                        logger.debug(f"Delaying output to {output.topic} by {output.delay_ms}ms")
                        time.sleep(output.delay_ms / 1000.0)

                    # Render template with context
                    if output.payload:
                        rendered_message = TemplateRenderer.render(
                            output.payload,
                            matcher_contexts
                        )
                    else:
                        # If no template, use the original message
                        rendered_message = json.dumps(message_data) if isinstance(message_data, dict) else str(message_data)

                    # Try to parse as JSON for consistency
                    try:
                        message_to_send = json.loads(rendered_message)
                    except json.JSONDecodeError:
                        message_to_send = rendered_message

                    # Apply fault injection if configured
                    if output.fault:
                        is_json = isinstance(message_to_send, dict)
                        should_produce, message_to_send = FaultInjector.apply_fault(message_to_send, output.fault, is_json)

                        if not should_produce:
                            logger.info(f"Message to {output.topic} was dropped due to fault injection")
                            continue

                        # Apply random latency if configured
                        random_latency_ms = FaultInjector.get_random_latency_ms(output.fault)
                        if random_latency_ms:
                            logger.debug(f"Applying random latency {random_latency_ms}ms")
                            time.sleep(random_latency_ms / 1000.0)

                    # Render headers if present
                    headers_to_send = None
                    if output.headers:
                        headers_to_send = {}
                        for header_key, header_value in output.headers.items():
                            rendered_header = TemplateRenderer.render(header_value, matcher_contexts)
                            headers_to_send[header_key] = rendered_header

                    # Produce to output topic with headers and schema_id
                    self.kafka_client.produce(
                        output.topic,
                        message_to_send,
                        headers=headers_to_send,
                        schema_id=output.schema_id
                    )
                    logger.info(f"Produced message to {output.topic} (rule: {rule.rule_name})")

                    # Handle message duplication if configured
                    if output.fault and FaultInjector.should_duplicate(output.fault):
                        logger.info(f"Duplicating message to {output.topic} (fault injection)")
                        self.kafka_client.produce(
                            output.topic,
                            message_to_send,
                            headers=headers_to_send,
                            schema_id=output.schema_id
                        )

                except Exception as e:
                    logger.error(f"Failed to execute output for {output.topic}: {e}")

        except Exception as e:
            logger.error(f"Error executing rule {rule.rule_name}: {e}")

