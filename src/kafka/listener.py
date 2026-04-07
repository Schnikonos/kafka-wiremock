"""
Kafka listener engine that processes messages and applies rules.
"""
import json
import logging
import threading
import time
import io
from typing import Dict, List, Set
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
from ..custom.placeholders import CustomPlaceholderRegistry

logger = logging.getLogger(__name__)


class KafkaListenerEngine:
    """Background listener engine that processes Kafka messages and applies rules."""

    def __init__(self, config_loader: ConfigLoader, kafka_client: KafkaClientWrapper,
                 bootstrap_servers: str = "localhost:9092",
                 custom_placeholder_registry: CustomPlaceholderRegistry = None):
        """
        Initialize the listener engine.

        Args:
            config_loader: Configuration loader instance
            kafka_client: Kafka client wrapper
            bootstrap_servers: Kafka bootstrap servers
            custom_placeholder_registry: Optional custom placeholder registry
        """
        self.config_loader = config_loader
        self.kafka_client = kafka_client
        self.bootstrap_servers = bootstrap_servers
        self.custom_placeholder_registry = custom_placeholder_registry
        self.consumers: Dict[str, KafkaConsumer] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self._running = False
        self._lock = threading.Lock()
        self._matcher_cache = {}

    def start(self) -> None:
        """Start the listener engine."""
        self._running = True
        self._start_listeners()
        logger.info("Kafka listener engine started")

    def stop(self) -> None:
        """Stop the listener engine."""
        self._running = False

        with self._lock:
            for thread in self.threads.values():
                thread.join(timeout=5)

            for consumer in self.consumers.values():
                consumer.close()

        logger.info("Kafka listener engine stopped")

    def _start_listeners(self) -> None:
        """Start listeners for all configured input topics."""
        topics = set()
        for rule in self.config_loader.get_all_rules():
            topics.add(rule.input_topic)

        with self._lock:
            for topic in topics:
                if topic not in self.threads:
                    thread = threading.Thread(
                        target=self._listen_topic,
                        args=(topic,),
                        daemon=True,
                        name=f"listener-{topic}"
                    )
                    thread.start()
                    self.threads[topic] = thread
                    logger.info(f"Started listener thread for topic: {topic}")

    def _listen_topic(self, topic: str) -> None:
        """Listen to a specific topic and process messages.

        Will only create a consumer if the topic exists.
        If the topic doesn't exist, will retry periodically.
        """
        retry_interval = 10  # seconds between retries for non-existent topics
        last_existence_check = 0
        topic_existed = False

        try:
            while self._running:
                current_time = time.time()

                # Check if topic exists (rate-limited every 10 seconds for non-existent topics)
                if not topic_existed and (current_time - last_existence_check) < retry_interval:
                    # Not yet time to re-check a non-existent topic
                    time.sleep(1)
                    continue

                # Check if topic exists
                if not self.kafka_client._verify_topic_exists(topic):
                    last_existence_check = current_time
                    if not topic_existed:
                        logger.debug(f"Topic '{topic}' does not exist yet. Will retry in {retry_interval}s")
                    time.sleep(1)
                    continue

                # Topic exists! Create consumer if we haven't already
                topic_existed = True
                if topic not in self.consumers:
                    consumer = KafkaConsumer(
                        topic,
                        bootstrap_servers=self.bootstrap_servers,
                        auto_offset_reset='latest',
                        group_id=f"wiremock-listener-{topic}",
                        consumer_timeout_ms=1000,
                        value_deserializer=lambda x: x if x is None else x,
                    )

                    with self._lock:
                        self.consumers[topic] = consumer

                    logger.info(f"Topic '{topic}' now available. Started listening to topic.")

                consumer = self.consumers[topic]

                try:
                    # Check for config changes every 30s
                    if self.config_loader.check_and_reload():
                        # Check if there are new topics to listen to
                        self._handle_config_reload()

                    # Check for custom placeholder changes
                    if self.custom_placeholder_registry and self.custom_placeholder_registry.check_and_reload():
                        logger.info("Custom placeholders reloaded")

                    # Poll for messages (timeout 5s)
                    messages = consumer.poll(timeout_ms=5000)

                    for topic_partition, records in messages.items():
                        for message in records:
                            self._process_message(topic, message)

                except Exception as e:
                    logger.error(f"Error polling topic {topic}: {e}")

        except Exception as e:
            logger.error(f"Unexpected error in listener thread for {topic}: {e}")
        finally:
            if topic in self.consumers:
                try:
                    self.consumers[topic].close()
                except Exception as e:
                    logger.debug(f"Error closing consumer for {topic}: {e}")
                del self.consumers[topic]
            logger.info(f"Listener thread for topic '{topic}' stopped")

    def _handle_config_reload(self) -> None:
        """Handle config reload by starting listeners for new topics."""
        topics = set()
        for rule in self.config_loader.get_all_rules():
            topics.add(rule.input_topic)

        with self._lock:
            current_topics = set(self.threads.keys())
            new_topics = topics - current_topics

            for topic in new_topics:
                logger.info(f"New topic detected in config: {topic}. Starting listener...")
                thread = threading.Thread(
                    target=self._listen_topic,
                    args=(topic,),
                    daemon=True,
                    name=f"listener-{topic}"
                )
                thread.start()
                self.threads[topic] = thread

    def _process_message(self, topic: str, message) -> None:
        """Process a single message and apply matching rules."""
        try:
            # Deserialize message value
            if message.value:
                try:
                    message_data = json.loads(message.value.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Try AVRO deserialization
                    if AVRO_AVAILABLE:
                        try:
                            if len(message.value) > 5 and message.value[0:1] == b'\x00':
                                # Confluent magic byte - skip first 5 bytes
                                bytes_reader = io.BytesIO(message.value[5:])
                            else:
                                bytes_reader = io.BytesIO(message.value)
                            message_data = fastavro.reader(bytes_reader).__next__()
                        except Exception as avro_err:
                            logger.debug(f"AVRO deserialization failed: {avro_err}")
                            message_data = message.value
                    else:
                        message_data = message.value
            else:
                message_data = None

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
                    # Stop after first match
                    break

        except Exception as e:
            logger.error(f"Error processing message from {topic}: {e}")

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

                except Exception as e:
                    logger.error(f"Failed to execute output for {output.topic}: {e}")

        except Exception as e:
            logger.error(f"Error executing rule {rule.rule_name}: {e}")

