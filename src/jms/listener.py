"""
JMS Listener engine that processes messages from JMS queues and applies rules.
Mirrors KafkaListenerEngine functionality for JMS queues.
"""
import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Set

try:
    import ibm_mq as MQ
    IBM_MQ_AVAILABLE = True
except ImportError:
    IBM_MQ_AVAILABLE = False

from ..rules.matcher import MatcherFactory
from ..rules.templater import TemplateRenderer
from ..config.loader import ConfigLoader
from ..config.jms_config_loader import JMSConfigLoader  # NEW
from ..config.models import Rule
from ..jms.registry import JMSClientRegistry  # NEW
from ..custom.placeholders import CustomPlaceholderRegistry
from ..fault.injector import FaultInjector
from ..test.cache import MessageCache

logger = logging.getLogger(__name__)


class JMSListenerEngine:
    """
    JMS listener engine that subscribes to JMS queues, applies matching rules, and produces messages.
    """

    def __init__(
        self,
        jms_registry: JMSClientRegistry,
        config_loader: ConfigLoader,
        jms_config_loader: JMSConfigLoader,
        kafka_client=None,  # KafkaClientWrapper — needed to produce rule output to Kafka topics
        message_cache: Optional[MessageCache] = None,
        custom_placeholder_registry: Optional[CustomPlaceholderRegistry] = None,
    ):
        """
        Initialize JMS listener engine.

        Args:
            jms_registry: Registry of JMS clients for different queue managers
            config_loader: Configuration loader
            jms_config_loader: JMS configuration loader
            kafka_client: Kafka client wrapper for producing Kafka outputs from rules
            message_cache: Optional message cache for test correlation
            custom_placeholder_registry: Optional custom placeholder registry
        """
        self.jms_registry = jms_registry
        self.jms_config_loader = jms_config_loader
        self.config_loader = config_loader
        self.kafka_client = kafka_client  # used in _execute_rule for msg_type=kafka outputs
        self.message_cache = message_cache
        self.custom_placeholder_registry = custom_placeholder_registry
        self.template_renderer = TemplateRenderer()
        self.fault_injector = FaultInjector()
        self.matcher_factory = MatcherFactory()

        self._running = False
        self._listener_thread = None
        self._stop_event = threading.Event()
        self._queues = set()
        self._queues_lock = threading.Lock()
        self._paused_queues: Set[str] = set()
        self._paused_queues_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start listening to JMS queues."""
        if self._running:
            logger.warning("JMS listener already running")
            return

        self._running = True
        self._stop_event.clear()
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()
        logger.info("JMS Listener started")

    def stop(self) -> None:
        """Stop listening to JMS queues."""
        if not self._running:
            return

        logger.info("Stopping JMS listener...")
        self._running = False
        self._stop_event.set()

        if self._listener_thread:
            self._listener_thread.join(timeout=5)
            logger.info("JMS listener stopped")

    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._running

    # ------------------------------------------------------------------
    # Per-queue pause / resume
    # ------------------------------------------------------------------

    def pause_queue(self, queue_name: str) -> bool:
        """Pause listening on a specific queue (messages stay in the queue).

        Returns True if the queue was known (active or already paused),
        False if the queue name is not in the current subscription set.
        """
        with self._paused_queues_lock:
            self._paused_queues.add(queue_name)
        with self._queues_lock:
            known = queue_name in self._queues
        if not known:
            logger.info(f"Paused JMS queue (not yet subscribed): {queue_name}")
        else:
            logger.info(f"Paused JMS queue listener: {queue_name}")
        return True  # Always succeeds — future subscriptions are also paused

    def resume_queue(self, queue_name: str) -> bool:
        """Resume listening on a previously paused queue."""
        with self._paused_queues_lock:
            was_paused = queue_name in self._paused_queues
            self._paused_queues.discard(queue_name)
        if was_paused:
            logger.info(f"Resumed JMS queue listener: {queue_name}")
        return was_paused

    def get_queue_status(self) -> Dict[str, Dict]:
        """Return a dict of all active queues with their enabled/paused state."""
        with self._queues_lock:
            active = set(self._queues)
        with self._paused_queues_lock:
            paused = set(self._paused_queues)

        result = {}
        for q in active | paused:
            result[q] = {
                "queue": q,
                "active": q in active,
                "paused": q in paused,
                "listening": q in active and q not in paused,
            }
        return result

    def get_listener_status(self) -> Dict:
        """Return overall listener engine status."""
        with self._queues_lock:
            active_queues = list(self._queues)
        with self._paused_queues_lock:
            paused_queues = list(self._paused_queues)

        poll_interval_ms = float(os.getenv("JMS_LISTENER_POLL_INTERVAL_MS", "100"))
        return {
            "running": self._running,
            "active_queues": active_queues,
            "paused_queues": paused_queues,
            "listening_queues": [q for q in active_queues if q not in paused_queues],
            "poll_interval_ms": poll_interval_ms,
        }

    def _listen_loop(self) -> None:
        # Use short non-blocking polls to avoid the IBM MQ "one MQGET-with-wait
        # per HCONN" restriction.  When MQGMO_WAIT is active on a shared hConn,
        # any concurrent put_message() or consume() call from the test runner
        # interrupts it with MQRC 2018, forcing a reconnect + 1 s sleep — making
        # test turnaround slow and unpredictable.  Using MQGMO_NO_WAIT (no_wait=True)
        # eliminates that conflict entirely; the short poll_interval compensates
        # for the lack of blocking wait.
        poll_interval = float(
            os.getenv("JMS_LISTENER_POLL_INTERVAL_MS", "100")
        ) / 1000.0  # default 100 ms

        while self._running and not self._stop_event.is_set():
            try:
                # Get current queues from rules
                self._update_subscriptions()

                # Poll each queue for messages
                for queue_name in list(self._queues):
                    if not self._running or self._stop_event.is_set():
                        break

                    # Skip paused queues
                    with self._paused_queues_lock:
                        if queue_name in self._paused_queues:
                            continue

                    try:
                        # Get JMS config to find queue manager for this queue
                        try:
                            jms_config = self.jms_config_loader.get_config(queue_name)
                            qm_ref = jms_config.queue_manager_ref if jms_config else "default"
                        except:
                            qm_ref = "default"

                        # Get the appropriate client from registry
                        client = self.jms_registry.get_client(qm_ref)

                        # Poll queue with no_wait=True to avoid MQGMO_WAIT conflicts
                        # on the shared HCONN (IBM MQ allows only one pending
                        # MQGET-with-wait per hConn; concurrent put/consume calls
                        # from tests would cancel it with MQRC 2018 otherwise).
                        messages = client.get_message(
                            destination=queue_name, max_messages=5, no_wait=True
                        )

                        for jms_msg in messages:
                            self._process_message(queue_name, jms_msg)

                    except Exception as e:
                        logger.error(f"Error polling queue {queue_name}: {e}")

                # Short sleep before next poll cycle
                self._stop_event.wait(timeout=poll_interval)

            except Exception as e:
                logger.error(f"Error in JMS listener loop: {e}")
                self._stop_event.wait(timeout=poll_interval)

    def _update_subscriptions(self) -> None:
        """Update the list of queues to subscribe to based on current rules."""
        try:
            rules = self.config_loader.get_all_rules()
            jms_rules = [r for r in rules if r.input_msg_type == "jms"]

            with self._queues_lock:
                current_queues = set()
                for rule in jms_rules:
                    current_queues.add(rule.input_topic)

                if current_queues != self._queues:
                    logger.debug(
                        f"Updated JMS queue subscriptions: {current_queues}"
                    )
                    self._queues = current_queues

        except Exception as e:
            logger.warning(f"Error updating queue subscriptions: {e}")

    def _process_message(self, queue_name: str, jms_message: 'JMSMessage') -> None:
        """Process a single message from a JMS queue and apply matching rules."""
        try:
            message_data = jms_message.payload
            message_headers = jms_message.headers or {}
            message_key = None

            # Parse payload if it's a JSON string
            if isinstance(message_data, str):
                try:
                    message_data = json.loads(message_data)
                except json.JSONDecodeError:
                    pass

            # Get rules for this queue
            rules = self.config_loader.get_rules_for_topic(queue_name)
            if not rules:
                logger.debug(f"No rules configured for queue {queue_name}")
                return

            # Cache the message for tests
            if self.message_cache:
                try:
                    self.message_cache.add_message(
                        topic=queue_name,
                        value=message_data,
                        message_format=jms_message.get("format", "json"),
                        headers=message_headers,
                        key=message_key,
                    )
                except Exception as e:
                    logger.debug(f"Failed to cache message: {e}")

            # Try matching rules
            for rule in rules:
                if rule.input_msg_type != "jms":
                    continue  # Skip non-JMS rules

                if self._evaluate_rule(rule, message_data, message_headers, message_key):
                    logger.info(f"Rule {rule.rule_name} matched for queue {queue_name}")
                    self._execute_rule(rule, message_data, message_headers, message_key)

                    # Mark message as consumed by rules
                    if self.message_cache:
                        try:
                            self.message_cache.mark_consumed_by_rules(
                                queue_name, 0
                            )
                        except Exception as e:
                            logger.debug(f"Failed to mark message as consumed: {e}")

                    break  # Stop after first match

        except Exception as e:
            logger.error(f"Error processing message from queue {queue_name}: {e}")

    def _evaluate_rule(
        self,
        rule: Rule,
        message_data: any,
        message_headers: dict = None,
        message_key: str = None,
    ) -> bool:
        """Evaluate if a message matches a rule."""
        try:
            # If no conditions, rule matches everything
            if not rule.conditions:
                return True

            # Check all conditions (AND logic)
            for condition in rule.conditions:
                matcher = self.matcher_factory.create(condition.type)

                if condition.type == "jsonpath":
                    match_condition = {
                        "path": condition.expression,
                        "value": condition.value,
                        "regex": condition.regex,
                    }
                    result = matcher.match(message_data, match_condition)
                elif condition.type == "header":
                    result = matcher.match(message_headers or {}, condition)
                elif condition.type == "key":
                    result = matcher.match(message_key, condition)
                else:
                    match_condition = (
                        condition.regex if condition.regex else condition.value
                    )
                    result = matcher.match(message_data, match_condition)

                if not result.matched:
                    return False

            return True

        except Exception as e:
            logger.warning(f"Error evaluating rule {rule.rule_name}: {e}")
            return False

    def _execute_rule(
        self,
        rule: Rule,
        message_data: any,
        message_headers: dict = None,
        message_key: str = None,
    ) -> None:
        """Execute a rule by producing output messages to Kafka or JMS."""
        try:
            if rule.skip:
                logger.debug(f"Rule {rule.rule_name} is skipped")
                return

            # Build initial context
            matcher_contexts = {}
            for condition in rule.conditions:
                matcher = self.matcher_factory.create(condition.type)

                if condition.type == "jsonpath":
                    match_condition = {
                        "path": condition.expression,
                        "value": condition.value,
                        "regex": condition.regex,
                    }
                    match_result = matcher.match(message_data, match_condition)
                elif condition.type == "header":
                    match_result = matcher.match(message_headers or {}, condition)
                elif condition.type == "key":
                    match_result = matcher.match(message_key, condition)
                else:
                    match_condition = (
                        condition.regex if condition.regex else condition.value
                    )
                    match_result = matcher.match(message_data, match_condition)

                matcher_contexts.update(match_result.context)

            # Add message data to context
            if isinstance(message_data, dict):
                matcher_contexts["message"] = message_data
                matcher_contexts["$"] = message_data
                for key, value in message_data.items():
                    matcher_contexts[key] = value
                    matcher_contexts[f"$.{key}"] = value

            # Execute custom placeholders
            if self.custom_placeholder_registry:
                try:
                    matcher_contexts = (
                        self.custom_placeholder_registry.execute_pipeline(
                            matcher_contexts
                        )
                    )
                except Exception as e:
                    logger.error(f"Error executing custom placeholder pipeline: {e}")

            # Produce output messages
            for output in rule.outputs:
                try:
                    if output.delay_ms and output.delay_ms > 0:
                        time.sleep(output.delay_ms / 1000.0)

                    # Render template
                    rendered_payload = (
                        self.template_renderer.render(
                            output.payload, matcher_contexts
                        )
                        if output.payload
                        else "{}"
                    )

                    # Parse rendered payload
                    try:
                        message_payload = json.loads(rendered_payload)
                    except json.JSONDecodeError:
                        message_payload = rendered_payload

                    # Check for fault injection
                    if output.fault:
                        fault_result = self.fault_injector.should_inject(output.fault)
                        if fault_result["should_inject"]:
                            logger.info(
                                f"Injecting fault for output to {output.topic}: {fault_result['type']}"
                            )
                            if fault_result["type"] == "drop":
                                continue

                    # Determine target client (Kafka or JMS)
                    msg_type = output.msg_type.lower()

                    if msg_type == "jms":
                        # Get JMS config to find which queue manager
                        jms_config = self.jms_config_loader.get_config(output.topic)
                        qm_ref = jms_config.queue_manager_ref if jms_config else "default"

                        # Override with explicit queue_manager_ref if provided in rule
                        if output.queue_manager_ref:
                            qm_ref = output.queue_manager_ref

                        try:
                            client = self.jms_registry.get_client(qm_ref)

                            message_id = client.put_message(
                                destination=output.topic,
                                payload=json.dumps(message_payload) if isinstance(message_payload, dict) else message_payload,
                                headers=output.headers,
                            )
                            if message_id:
                                logger.info(
                                    f"Output {message_id} sent to JMS queue {output.topic} "
                                    f"(queue_manager={qm_ref})"
                                )
                                # Cache the produced message so test expectations can
                                # observe it from the in-memory cache rather than
                                # polling IBM MQ directly (which would race with the
                                # listener's own MQGET on the shared hConn).
                                if self.message_cache:
                                    try:
                                        self.message_cache.add_message(
                                            topic=output.topic,
                                            value=message_payload,
                                            message_format="json",
                                            timestamp=int(time.time() * 1000),
                                            headers=output.headers or {},
                                            key=None,
                                        )
                                    except Exception as cache_err:
                                        logger.debug(f"Failed to cache JMS output message: {cache_err}")
                        except ValueError as e:
                            logger.error(
                                f"Error getting JMS client for queue_manager {qm_ref}: {e}"
                            )
                    else:
                        # Send to Kafka topic via the kafka_client passed at construction.
                        if self.kafka_client is None:
                            logger.error(
                                f"Cannot send to Kafka topic {output.topic}: "
                                f"no kafka_client was provided to JMSListenerEngine. "
                                f"Pass kafka_client= when constructing JMSListenerEngine."
                            )
                        else:
                            try:
                                message_id = self.kafka_client.produce(
                                    topic=output.topic,
                                    message=message_payload,
                                    schema_id=output.schema_id,
                                )
                                if message_id:
                                    logger.info(
                                        f"Output {message_id} sent to Kafka topic {output.topic}"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Error sending to Kafka topic {output.topic}: {e}"
                                )

                except Exception as e:
                    logger.error(f"Error producing output message to {output.topic}: {e}")

        except Exception as e:
            logger.error(f"Error executing rule {rule.rule_name}: {e}")
