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
from confluent_kafka import Consumer, KafkaError, TopicPartition

try:
    import fastavro
    AVRO_AVAILABLE = True
except ImportError:
    AVRO_AVAILABLE = False

from ..rules.matcher import MatcherFactory, is_verbose as _matcher_is_verbose
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
                 schema_registry: SchemaRegistry = None,
                 http_executor=None,     # Optional HttpExecutor for type=http rule outputs
                 db_registry=None,       # Optional DBRegistry for type=db rule outputs
                 topic_config_loader=None):  # Optional TopicConfigLoader for correlation
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
            http_executor: Optional HttpExecutor for type=http rule outputs
            db_registry: Optional DBRegistry for type=db rule outputs
            topic_config_loader: Optional TopicConfigLoader for correlation extraction/propagation
        """
        self.config_loader = config_loader
        self.kafka_client = kafka_client
        self.bootstrap_servers = bootstrap_servers
        self.base_config = kafka_client.base_config if hasattr(kafka_client, 'base_config') else {}
        self.custom_placeholder_registry = custom_placeholder_registry
        self.message_cache = message_cache
        self.topic_metadata_manager = topic_metadata_manager
        self.schema_registry = schema_registry
        self.http_executor = http_executor  # Optional; HTTP outputs skipped if None
        self.db_registry = db_registry       # Optional; DB outputs skipped if None
        self.topic_config_loader = topic_config_loader  # Optional; correlation skipped if None

        self.consumer: Optional[Consumer] = None
        self.listener_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._last_subscription_update = 0
        self._subscription_update_event = threading.Event()
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
        Signals the listener thread to perform an immediate subscription update
        so topics are registered without waiting for the 30-second refresh cycle.

        Args:
            topic: Topic name to listen to
            timeout_seconds: Maximum time to wait for subscription

        Returns:
            True if subscription includes topic within timeout, False if timeout
        """
        # Force an immediate subscription update in the listener thread
        self._last_subscription_update = 0
        self._subscription_update_event.set()

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
                            consumer_config = self.base_config.copy()
                            consumer_config.update({
                                'group.id': 'wiremock-listener',
                                'auto.offset.reset': 'latest',
                                'enable.auto.commit': True,
                                'auto.commit.interval.ms': 5000,
                                # Keep broker-side fetch wait short so messages reach
                                # the cache quickly.  The listener thread already calls
                                # poll() in a tight loop, so a large value here would
                                # add unnecessary latency to test expectations.
                                'fetch.wait.max.ms': 10,
                            })
                            self.consumer = Consumer(consumer_config)
                            retry_count = 0
                            logger.info("Connected to Kafka consumer")
                            with self._lock:
                                self.consumer = self.consumer
                        except Exception as e:
                            retry_count += 1
                            logger.warning(f"Failed to create consumer (attempt {retry_count}/{max_retries}): {e}")
                            time.sleep(2)
                            continue

                    # Update subscription every 30 seconds OR when explicitly requested
                    current_time = time.time()
                    if self._subscription_update_event.is_set() or current_time - self._last_subscription_update > 30:
                        self._subscription_update_event.clear()
                        self._update_subscription()
                        self._last_subscription_update = time.time()

                    # Check for config changes
                    if self.config_loader.check_and_reload():
                        logger.debug("Config reloaded, will update topic subscription on next cycle")

                    # Check for custom placeholder changes
                    if self.custom_placeholder_registry and self.custom_placeholder_registry.check_and_reload():
                        logger.info("Custom placeholders reloaded")

                    # Poll for messages (short timeout so we can react to subscription-update requests quickly)
                    msg = self.consumer.poll(timeout=1.0)

                    if msg is None:
                        # Timeout
                        continue

                    if msg.error():
                        if msg.error().code() == KafkaError._PARTITION_EOF:
                            logger.debug(f"End of partition reached")
                        else:
                            logger.error(f"Consumer error: {msg.error()}")
                        continue

                    topic = msg.topic()
                    self._process_message(topic, msg)

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
                    configured_topics.add(rule.input_destination)
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

            # Process headers
            message_headers = None
            if message.headers():
                message_headers = {}
                for key, val in message.headers():
                    if isinstance(val, bytes):
                        message_headers[key] = val.decode('utf-8')
                    else:
                        message_headers[key] = val

            # Extract message key
            message_key = None
            if message.key():
                message_key = message.key().decode('utf-8') if isinstance(message.key(), bytes) else str(message.key())

            # Add message to cache with format information
            if self.message_cache:
                try:
                    self.message_cache.add_message(
                        topic=topic,
                        value=message_data,
                        message_format=message_format,
                        timestamp=message.timestamp()[1] if message.timestamp() else 0,
                        partition=message.partition(),
                        offset=message.offset(),
                        headers=message_headers,
                        key=message_key
                    )
                except Exception as e:
                    logger.debug(f"Failed to add message to cache: {e}")

            # Get rules for this topic
            rules = self.config_loader.get_rules_for_topic(topic)

            if not rules:
                logger.debug(f"No rules configured for topic: {topic}")
                return

            # Verbose: log the incoming message once before checking all rules
            if _matcher_is_verbose():
                try:
                    import json as _json
                    msg_repr = _json.dumps(message_data, default=str)[:800]
                except Exception:
                    msg_repr = repr(message_data)[:800]
                logger.info(
                    f"[VERBOSE-RULES] Received message on topic={topic!r} "
                    f"key={message_key!r} headers={message_headers} "
                    f"payload={msg_repr} — trying {len(rules)} rule(s)"
                )

            # Evaluate rules in priority order
            for rule in rules:
                if self._evaluate_rule(rule, message_data, message_headers=message_headers, message_key=message_key):
                    logger.info(f"Rule matched: {rule.rule_name} for topic {topic}")
                    self._execute_rule(rule, message_data, message_headers=message_headers, message_key=message_key)

                    # Mark message as consumed by rules
                    if self.message_cache:
                        try:
                            self.message_cache.mark_consumed_by_rules(topic, message.offset())
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
            if not kafka_message.value():
                return None, "null"

            # Try to deserialize based on topic type
            if topic_type == "avro":
                # Try Schema Registry first if available
                if self.schema_registry:
                    message_data, fmt = self.schema_registry.decode(kafka_message.value())
                    if message_data is not None:
                        return message_data, fmt

                # Fallback to raw AVRO deserialization
                if AVRO_AVAILABLE:
                    try:
                        if len(kafka_message.value()) > 5 and kafka_message.value()[0:1] == b'\x00':
                            bytes_reader = io.BytesIO(kafka_message.value()[5:])
                        else:
                            bytes_reader = io.BytesIO(kafka_message.value())
                        message_data = fastavro.reader(bytes_reader).__next__()
                        return message_data, "avro"
                    except Exception as e:
                        logger.debug(f"AVRO fallback deserialization failed: {e}")

                # Fall through to JSON attempt

            elif topic_type == "bytes":
                # Try JSON first, then return as bytes
                try:
                    return json.loads(kafka_message.value().decode('utf-8')), "json"
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return kafka_message.value(), "bytes"

            # Default: try JSON
            try:
                return json.loads(kafka_message.value().decode('utf-8')), "json"
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Try AVRO as fallback
                if AVRO_AVAILABLE:
                    try:
                        if len(kafka_message.value()) > 5 and kafka_message.value()[0:1] == b'\x00':
                            bytes_reader = io.BytesIO(kafka_message.value()[5:])
                        else:
                            bytes_reader = io.BytesIO(kafka_message.value())
                        message_data = fastavro.reader(bytes_reader).__next__()
                        return message_data, "avro"
                    except Exception:
                        pass

                # Last resort: return bytes as-is
                return kafka_message.value(), "bytes"

        except Exception as e:
            logger.error(f"Error deserializing message: {e}")
            return None, "error"

    def _evaluate_rule(self, rule: Rule, message_data: any, message_headers: dict = None, message_key: str = None) -> bool:
        """Evaluate if a message matches a rule."""
        try:
            # Verbose: log the message being evaluated against this rule
            if _matcher_is_verbose():
                try:
                    import json as _json
                    msg_repr = _json.dumps(message_data, default=str)[:500]
                except Exception:
                    msg_repr = repr(message_data)[:500]
                logger.info(
                    f"[VERBOSE-RULES] Evaluating rule={rule.rule_name!r} "
                    f"conditions={len(rule.conditions)} "
                    f"message={msg_repr} "
                    f"headers={message_headers} key={message_key!r}"
                )

            # If no conditions, rule matches everything (wildcard)
            if not rule.conditions:
                if _matcher_is_verbose():
                    logger.info(f"[VERBOSE-RULES] rule={rule.rule_name!r} → MATCH (no conditions = wildcard)")
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
                    result = matcher.match(message_data, match_condition)
                elif condition.type == 'header':
                    # For header matching, pass headers dict
                    result = matcher.match(message_headers or {}, condition)
                elif condition.type == 'key':
                    # For key matching, pass message key
                    result = matcher.match(message_key, condition)
                else:
                    # For other matchers, use the value or regex
                    match_condition = condition.regex if condition.regex else condition.value
                    result = matcher.match(message_data, match_condition)

                if not result.matched:
                    if _matcher_is_verbose():
                        logger.info(
                            f"[VERBOSE-RULES] rule={rule.rule_name!r} → NO MATCH "
                            f"(condition {condition.type} failed first)"
                        )
                    return False

            if _matcher_is_verbose():
                logger.info(f"[VERBOSE-RULES] rule={rule.rule_name!r} → MATCH (all {len(rule.conditions)} conditions passed)")
            return True

        except Exception as e:
            logger.warning(f"Error evaluating rule {rule.rule_name}: {e}")
            return False

    def _execute_rule(self, rule: Rule, message_data: any, message_headers: dict = None, message_key: str = None) -> None:
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
                    match_result = matcher.match(message_data, match_condition)
                elif condition.type == 'header':
                    # For header matching, pass headers dict
                    match_result = matcher.match(message_headers or {}, condition)
                elif condition.type == 'key':
                    # For key matching, pass message key
                    match_result = matcher.match(message_key, condition)
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

            # Add input message key to context (only if not None)
            if message_key:
                matcher_contexts['inputKey'] = message_key

            # Add input headers to context
            if message_headers:
                matcher_contexts['headerMap'] = message_headers
                # Also add individual header accessors with header. prefix
                for header_name, header_value in message_headers.items():
                    matcher_contexts[f'header.{header_name}'] = header_value

            # Extract correlation ID from input message using topic-config or rule-level override
            correlation_id = None
            if self.topic_config_loader:
                try:
                    from ..config.topic_config import CorrelationConfig, CorrelationExtractRule
                    from ..messaging.correlation import extract_correlation_id as _extract_corr

                    corr_config = None
                    # Rule-level correlation.extract overrides topic-level config
                    if rule.correlation and rule.correlation.extract:
                        extract_rules = []
                        for idx, r in enumerate(rule.correlation.extract):
                            extract_rules.append(CorrelationExtractRule(
                                from_type=r.get("from", "header"),
                                name=r.get("name"),
                                expression=r.get("expression"),
                                priority=r.get("priority", idx),
                            ))
                        corr_config = CorrelationConfig(extract=extract_rules)
                    else:
                        topic_cfg = self.topic_config_loader.get_topic_config(rule.input_destination)
                        if topic_cfg and topic_cfg.correlation:
                            corr_config = topic_cfg.correlation

                    if corr_config:
                        correlation_id = _extract_corr(message_data, message_headers, corr_config)
                        if correlation_id:
                            matcher_contexts['correlationId'] = correlation_id
                            logger.debug(f"Extracted correlationId={correlation_id!r} for rule {rule.rule_name}")
                except Exception as _corr_err:
                    logger.debug(f"Correlation extraction skipped: {_corr_err}")

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
                        logger.debug(f"Delaying output to {output.destination} by {output.delay_ms}ms")
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
                            logger.info(f"Message to {output.destination} was dropped due to fault injection")
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

                    # Determine output type early so correlation propagation can check it
                    output_type = getattr(output, 'msg_type', 'kafka').lower()

                    # Apply correlation propagation for Kafka/JMS outputs (not HTTP/DB)
                    if correlation_id and output_type not in ('http', 'db'):
                        try:
                            from ..messaging.correlation import apply_propagation as _apply_prop
                            from ..config.topic_config import CorrelationConfig, CorrelationPropagateRule

                            out_corr_config = None
                            # Output-level override takes precedence
                            if output.correlation and output.correlation.to_headers:
                                out_corr_config = CorrelationConfig(
                                    propagate=CorrelationPropagateRule(
                                        to_headers=output.correlation.to_headers
                                    )
                                )
                            elif self.topic_config_loader:
                                _dest_for_lookup = output.destination
                                out_topic_cfg = self.topic_config_loader.get_topic_config(_dest_for_lookup)
                                if out_topic_cfg and out_topic_cfg.correlation:
                                    out_corr_config = out_topic_cfg.correlation

                            if out_corr_config:
                                headers_to_send = _apply_prop(
                                    headers_to_send, correlation_id, out_corr_config
                                )
                        except Exception as _prop_err:
                            logger.debug(f"Correlation propagation skipped: {_prop_err}")

                    # Render key if present
                    key_to_send = None
                    if output.key:
                        key_to_send = TemplateRenderer.render(output.key, matcher_contexts)
                        logger.debug(f"Rendered key template '{output.key}' to: '{key_to_send}'")
                        # If rendering resulted in the original template string (placeholder not found), set to None
                        if key_to_send.startswith("{{") and key_to_send.endswith("}}"):
                            logger.debug(f"Message key template could not be resolved: {key_to_send}, setting to None")
                            key_to_send = None

                    # Apply messageKey poison pill if configured
                    if output.fault and output.fault.poison_pill > 0 and 'messageKey' in output.fault.poison_pill_type:
                        if FaultInjector._should_fault(output.fault.poison_pill):
                            key_to_send = FaultInjector.apply_messagekey_poison_pill(key_to_send)

                    # Produce to correct destination based on output type (already set above)
                    if output_type == 'db':
                        # Execute DB action as rule side-effect
                        if not self.db_registry:
                            logger.error(
                                f"DB registry not initialized; cannot execute db output "
                                f"(rule: {rule.rule_name}). Wire db_registry into KafkaListenerEngine."
                            )
                        else:
                            if not output.db_query:
                                logger.error(
                                    f"DB output in rule {rule.rule_name} missing 'query' field"
                                )
                            else:
                                from ..db.executor import DBExecutor as _DBExecutor
                                _db_exec = _DBExecutor(self.db_registry)
                                rendered_db_query = TemplateRenderer.render(
                                    output.db_query, matcher_contexts
                                )
                                rendered_db_params = None
                                if output.db_params:
                                    rendered_db_params = {
                                        k: TemplateRenderer.render(str(v), matcher_contexts)
                                        for k, v in output.db_params.items()
                                    }
                                try:
                                    db_ctx = _db_exec.execute(
                                        db_ref=output.db_ref,
                                        operation=output.db_operation,
                                        query=rendered_db_query,
                                        params=rendered_db_params,
                                        step_id=output.db_step_id,
                                    )
                                    matcher_contexts.update(db_ctx)
                                    _result_summary = ""
                                    if output.db_step_id:
                                        _pfx = f"db.{output.db_step_id}"
                                        _ra = db_ctx.get(f"{_pfx}.rows_affected")
                                        _rc = db_ctx.get(f"{_pfx}.row_count")
                                        _gk = db_ctx.get(f"{_pfx}.generated_key")
                                        if _ra is not None:
                                            _result_summary = f" rows_affected={_ra}"
                                        if _rc is not None:
                                            _result_summary += f" row_count={_rc}"
                                        if _gk is not None:
                                            _result_summary += f" generated_key={_gk!r}"
                                        if _matcher_is_verbose():
                                            _rows = db_ctx.get(f"{_pfx}.rows")
                                            if _rows is not None:
                                                _result_summary += f" rows={_rows}"
                                    logger.info(
                                        f"DB {output.db_operation} executed"
                                        f"{_result_summary} "
                                        f"(rule: {rule.rule_name}, db: {output.db_ref})"
                                    )
                                except Exception as db_err:
                                    logger.error(
                                        f"DB output failed for rule {rule.rule_name}: {db_err}"
                                    )
                    elif output_type == 'http':
                        # Fire HTTP call (synchronous bridge from listener thread)
                        if not self.http_executor:
                            logger.error(
                                f"HTTP executor not initialized; cannot call {output.destination} "
                                f"(rule: {rule.rule_name}). Wire http_executor into KafkaListenerEngine."
                            )
                        else:
                            import asyncio as _asyncio
                            rendered_url = TemplateRenderer.render(output.destination, matcher_contexts)
                            rendered_query = None
                            if output.query_params:
                                rendered_query = {k: TemplateRenderer.render(v, matcher_contexts) for k, v in output.query_params.items()}
                            try:
                                http_result = _asyncio.run(
                                    self.http_executor.execute(
                                        url=rendered_url,
                                        method=output.method,
                                        payload=rendered_message if output.payload else None,
                                        headers=headers_to_send,
                                        query_params=rendered_query,
                                        auth_ref=output.auth_ref,
                                        tls_ref=output.tls_ref,
                                        timeout_ms=output.http_timeout_ms,
                                    )
                                )
                                logger.info(
                                    f"HTTP {output.method} {rendered_url} → {http_result.status_code} "
                                    f"(rule: {rule.rule_name})"
                                )
                            except Exception as http_err:
                                logger.error(f"HTTP output failed for {rendered_url}: {http_err}")
                    else:
                        # Default: produce to Kafka topic
                        # Render destination to support dynamic topic names e.g. {{$.replyTopic}}
                        rendered_destination = TemplateRenderer.render(output.destination, matcher_contexts)
                        self.kafka_client.produce(
                            rendered_destination,
                            message_to_send,
                            headers=headers_to_send,
                            key=key_to_send,
                            schema_id=output.schema_id
                        )
                        logger.info(f"Produced message to {rendered_destination} (rule: {rule.rule_name})")

                    # Handle message duplication if configured (not for HTTP)
                    if output_type != 'http' and output.fault and FaultInjector.should_duplicate(output.fault):
                        logger.info(f"Duplicating message to {rendered_destination} (fault injection)")
                        self.kafka_client.produce(
                            rendered_destination,
                            message_to_send,
                            headers=headers_to_send,
                            key=key_to_send,
                            schema_id=output.schema_id
                        )

                except Exception as e:
                    logger.error(f"Failed to execute output for {output.destination}: {e}")

        except Exception as e:
            logger.error(f"Error executing rule {rule.rule_name}: {e}")

