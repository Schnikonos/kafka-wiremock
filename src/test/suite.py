"""
Test Suite execution engine - SIMPLIFIED with flat list structure.
Orchestrates test execution, message injection, and result aggregation.
"""
import json
import logging
import asyncio
import time
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JSONPathError

from .loader import TestDefinition, TestInjection, TestExpectation, TestScript
from ..kafka.client import KafkaClientWrapper
from ..rules.matcher import MatcherFactory
from ..rules.templater import TemplateRenderer
from ..custom.placeholders import CustomPlaceholderRegistry
from ..fault.injector import FaultInjector
from .logger import TestLogger

logger = logging.getLogger(__name__)


@dataclass
class InjectedMessage:
    """Captured injected message for context."""
    message_id: str
    topic: str
    payload: Any  # Parsed JSON or string
    headers: Optional[Dict[str, str]] = None
    timestamp: int = 0  # Milliseconds
    status: str = "ok"  # "ok" or error message


@dataclass
class ReceivedMessage:
    """Captured received message from Kafka."""
    value: Any  # Parsed JSON or string
    timestamp: int = 0
    partition: int = 0
    offset: int = 0
    headers: Optional[Dict[str, str]] = None


@dataclass
class ExpectationResult:
    """Result for a single expectation."""
    index: int
    topic: str
    expected: int  # Expected count (usually 1 if source_id used, else >= 1)
    received: int  # Actual count received
    status: str  # "MATCHED", "TIMEOUT", "NO_MATCH"
    elapsed_ms: int = 0
    received_messages: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ThenResult:
    """Result of 'then' phase."""
    expectations: List[ExpectationResult] = field(default_factory=list)
    script_error: Optional[str] = None


@dataclass
class WhenResult:
    """Result of 'when' phase."""
    injected: List[Dict[str, Any]] = field(default_factory=list)
    faulted_injections: List[str] = field(default_factory=list)  # message_ids with faults (and check_result=False)
    script_error: Optional[str] = None


@dataclass
class TestResult:
    """Result of a single test execution."""
    test_id: str
    status: str  # "PASSED", "FAILED", "SKIPPED", "TIMEOUT"
    elapsed_ms: int = 0
    when_result: WhenResult = field(default_factory=WhenResult)
    then_result: ThenResult = field(default_factory=ThenResult)
    errors: List[str] = field(default_factory=list)


class TestExecutor:
    """Executes individual test definitions."""

    def __init__(
        self,
        kafka_client: KafkaClientWrapper,
        custom_placeholder_registry: Optional[CustomPlaceholderRegistry] = None,
        test_suite_dir: str = "/testSuite",
        message_cache = None,
        listener_engine = None
    ):
        """Initialize test executor."""
        self.kafka_client = kafka_client
        self.custom_placeholder_registry = custom_placeholder_registry or CustomPlaceholderRegistry()
        self.matcher_factory = MatcherFactory()
        self.test_suite_dir = test_suite_dir
        self.message_cache = message_cache  # Optional cache for test message queries
        self.listener_engine = listener_engine  # Optional listener engine for ensuring topics are ready

    async def run_test(self, test: TestDefinition, test_file_path: Optional[Path] = None, verbose: bool = False) -> TestResult:
        """Execute a single test."""
        start_time = time.time()
        result = TestResult(test_id=test.name, status="PENDING")

        # Log test information
        logger.info(f"Running test: {test.name}")
        logger.info(f"  Test object file_path attribute: {test.file_path}")
        logger.info(f"  test_file_path parameter: {test_file_path}")
        logger.info(f"  Verbose mode: {verbose}")

        # Initialize test logger if file path provided
        test_logger = None
        if test_file_path:
            test_file_path = Path(test_file_path).resolve()  # Convert to absolute path
            logger.info(f"Test {test.name} will log to: {test_file_path}")
            test_logger = TestLogger(test_file_path, verbose=verbose)
        elif test.file_path:
            # Fallback: use file_path from test definition if not provided as parameter
            logger.info(f"Using file_path from test definition: {test.file_path}")
            test_file_path = Path(test.file_path).resolve()
            test_logger = TestLogger(test_file_path, verbose=verbose)
        else:
            logger.warning(f"Test {test.name} has no file path - logging disabled")

        try:
            if test.skip:
                result.status = "SKIPPED"
                result.elapsed_ms = int((time.time() - start_time) * 1000)
                return result

            # Phase 1: Execute "when"
            when_result = await self._execute_when(test, test_logger)
            result.when_result = when_result

            if when_result.script_error:
                result.status = "FAILED"
                result.errors.append(f"When phase failed: {when_result.script_error}")
                result.elapsed_ms = int((time.time() - start_time) * 1000)
                if test_logger:
                    test_logger.write_log_file(test.name, result.status, result.elapsed_ms, result.errors)
                return result

            # Phase 2: Execute "then"
            then_result = await self._execute_then(test, result.when_result, test_logger, test_start_time=start_time)
            result.then_result = then_result

            if then_result.script_error:
                result.status = "FAILED"
                result.errors.append(f"Then phase failed: {then_result.script_error}")
                result.elapsed_ms = int((time.time() - start_time) * 1000)
                if test_logger:
                    test_logger.write_log_file(test.name, result.status, result.elapsed_ms, result.errors)
                return result

            # Check if all expectations matched
            all_matched = all(exp.status == "MATCHED" for exp in then_result.expectations)
            if all_matched and not result.errors:
                result.status = "PASSED"
            else:
                result.status = "FAILED"
                for exp in then_result.expectations:
                    if exp.status != "MATCHED":
                        result.errors.append(
                            f"Expectation for {exp.topic}: {exp.status} "
                            f"(expected {exp.expected}, received {exp.received})"
                        )

        except Exception as e:
            logger.exception(f"Test {test.name} execution failed")
            result.status = "FAILED"
            result.errors.append(f"Test execution error: {str(e)}")

        result.elapsed_ms = int((time.time() - start_time) * 1000)

        # Write log file
        if test_logger:
            test_logger.write_log_file(test.name, result.status, result.elapsed_ms, result.errors)

        return result

    async def _execute_when(self, test: TestDefinition, test_logger: Optional[TestLogger] = None) -> WhenResult:
        """Execute 'when' phase: injections and scripts, sequential."""
        result = WhenResult()
        injected_messages = []
        context = {}

        try:
            # Process items sequentially
            for item in test.when.items:
                if isinstance(item, TestInjection):
                    try:
                        # Build template context
                        template_context = {
                            "testId": test.name,
                            "uuid": str(__import__('uuid').uuid4()),
                            "now": datetime.now(timezone.utc).isoformat() + "Z",
                            "randomInt": lambda min_val=0, max_val=100: __import__('random').randint(min_val, max_val)
                        }

                        # Add custom placeholders
                        if self.custom_placeholder_registry:
                            placeholders = self.custom_placeholder_registry.get_all_placeholders()
                            for name, func in placeholders.items():
                                try:
                                    template_context[name] = func(template_context)
                                except Exception as e:
                                    logger.warning(f"Failed to execute custom placeholder {name}: {e}")

                        template_context.update(context)

                        # Render and inject
                        rendered_payload = TemplateRenderer.render(item.payload, template_context)
                        rendered_headers = None
                        if item.headers:
                            rendered_headers = {
                                k: TemplateRenderer.render(v, template_context)
                                for k, v in item.headers.items()
                            }

                        try:
                            payload_obj = json.loads(rendered_payload)
                        except json.JSONDecodeError:
                            payload_obj = rendered_payload

                        # Apply fault injection if configured
                        fault_applied = False
                        if item.fault:
                            is_json = isinstance(payload_obj, dict)
                            should_produce, payload_obj = FaultInjector.apply_fault(payload_obj, item.fault, is_json)

                            if not should_produce:
                                logger.info(f"Test injection message to {item.topic} was dropped due to fault injection")
                                fault_applied = True
                                # Don't add to injected messages since it was dropped
                                continue

                            # Apply random latency if configured
                            random_latency_ms = FaultInjector.get_random_latency_ms(item.fault)
                            if random_latency_ms:
                                logger.debug(f"Applying random latency {random_latency_ms}ms to test injection")
                                await asyncio.sleep(random_latency_ms / 1000.0)

                        self.kafka_client.produce(
                            topic=item.topic,
                            message=payload_obj,
                            headers=rendered_headers
                        )

                        # Handle message duplication if configured
                        if item.fault and FaultInjector.should_duplicate(item.fault):
                            logger.info(f"Duplicating test injection message to {item.topic} (fault injection)")
                            self.kafka_client.produce(
                                topic=item.topic,
                                message=payload_obj,
                                headers=rendered_headers
                            )

                        injected_msg = InjectedMessage(
                            message_id=item.message_id,
                            topic=item.topic,
                            payload=payload_obj,
                            headers=rendered_headers,
                            timestamp=int(time.time() * 1000),
                            status="ok"
                        )
                        injected_messages.append(injected_msg)

                        # Track if this injection had fault with check_result=False
                        # (if check_result=True, we still want to validate)
                        if item.fault and not item.fault.check_result:
                            result.faulted_injections.append(item.message_id)
                            logger.info(f"Marked injection {item.message_id} as faulted (check_result=False)")

                        # Log sent message
                        if test_logger:
                            test_logger.log_sent_message(
                                topic=item.topic,
                                payload=payload_obj,
                                message_id=item.message_id,
                                headers=rendered_headers
                            )

                        if item.delay_ms > 0:
                            await asyncio.sleep(item.delay_ms / 1000.0)

                    except Exception as e:
                        logger.error(f"Failed to inject message {item.message_id}: {e}")
                        result.script_error = str(e)
                        break

                elif isinstance(item, TestScript):
                    # Execute script
                    try:
                        script_context = {
                            "current_injections": [asdict(m) for m in injected_messages],
                            "custom_placeholders": self.custom_placeholder_registry.get_all_placeholders() or {},
                            "kafka_client": self.kafka_client,
                            "context": context
                        }
                        exec(item.script, script_context)
                        if "context" in script_context:
                            context.update(script_context["context"])
                    except Exception as e:
                        logger.error(f"When script failed: {e}")
                        result.script_error = str(e)
                        break

            result.injected = [
                {"message_id": m.message_id, "topic": m.topic, "status": m.status, "payload": m.payload}
                for m in injected_messages
            ]

        except Exception as e:
            logger.error(f"When phase failed: {e}")
            result.script_error = str(e)

        return result

    async def _execute_then(self, test: TestDefinition, when_result: WhenResult, test_logger: Optional[TestLogger] = None, test_start_time: float = None) -> ThenResult:
        """Execute 'then' phase: expectations and scripts, sequential."""
        result = ThenResult()
        context = {}
        collected_results = []

        try:
            # Build injections dict for correlation
            injections_dict = {m["message_id"]: m for m in when_result.injected}

            # Process items sequentially
            for item in test.then.items:
                if isinstance(item, TestExpectation):
                    # Collect expectation messages
                    exp_result = await self._collect_expectation_messages(
                        item, len(collected_results), when_result, injections_dict, context, test_logger, test_start_time=test_start_time
                    )
                    result.expectations.append(exp_result)
                    collected_results.append(exp_result)

                elif isinstance(item, TestScript):
                    # Execute script
                    try:
                        script_context = {
                            "current_expectations": collected_results,
                            "custom_placeholders": self.custom_placeholder_registry.get_all_placeholders() or {},
                            "kafka_client": self.kafka_client,
                            "context": context
                        }
                        exec(item.script, script_context)
                        if "context" in script_context:
                            context.update(script_context["context"])
                    except Exception as e:
                        logger.error(f"Then script failed: {e}")
                        result.script_error = str(e)
                        break

        except Exception as e:
            logger.error(f"Then phase failed: {e}")
            result.script_error = str(e)

        return result

    async def _collect_expectation_messages(
        self,
        expectation: TestExpectation,
        exp_idx: int,
        when_result: WhenResult,
        injections_dict: Dict[str, Any],
        context: Dict[str, Any],
        test_logger: Optional[TestLogger] = None,
        test_start_time: float = None
    ) -> ExpectationResult:
        """Collect messages for a single expectation with correlation."""
        exp_result = ExpectationResult(
            index=exp_idx,
            topic=expectation.topic,
            expected=1,
            received=0,
            status="PENDING"
        )

        start_time = time.time()

        try:
            # Check if this expectation is correlated to a faulted injection (and check_result=False)
            if expectation.correlate and expectation.correlate.message_id:
                corr_msg_id = expectation.correlate.message_id
                if corr_msg_id in when_result.faulted_injections:
                    logger.info(f"Skipping expectation for topic {expectation.topic} (correlated to faulted injection {corr_msg_id} with check_result=False)")
                    exp_result.status = "SKIPPED_DUE_TO_FAULT"
                    exp_result.elapsed_ms = 0
                    return exp_result

            # ... existing correlation and message collection code ..."""
            # Resolve correlation if specified
            correlation_value = None
            if expectation.correlate:
                corr = expectation.correlate
                if corr.message_id and corr.source:
                    # Extract field from injected message
                    injected_data = injections_dict.get(corr.message_id)
                    if injected_data:
                        try:
                            payload = injected_data.get("payload")
                            if payload:
                                # Determine source type and extract value
                                if "jsonpath" in corr.source:
                                    expr_str = corr.source["jsonpath"]
                                    source_expr = jsonpath_parse(expr_str)
                                    matches = source_expr.find(payload)
                                    correlation_value = matches[0].value if matches else None
                                elif "header" in corr.source:
                                    # Headers are in injected_data
                                    header_name = corr.source["header"]
                                    headers = injected_data.get("headers", {})
                                    correlation_value = headers.get(header_name)
                                
                                if correlation_value is None:
                                    logger.warning(f"Could not extract correlation from source {corr.source}")
                            else:
                                logger.warning(f"No payload in injected message {corr.message_id}")
                        except Exception as e:
                            logger.warning(f"Failed to extract correlation value: {e}")
                            correlation_value = None
                    else:
                        exp_result.error = f"Message not found: {corr.message_id}"
                        exp_result.status = "NO_MATCH"
                        exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                        return exp_result
                elif corr.message_id:
                    # message_id without source - will match any message from that injection
                    logger.debug(f"Using message_id {corr.message_id} without source for correlation")

            # Note: We don't check if listener is subscribed to this topic
            # because the listener only listens to INPUT topics (from rules),
            # not OUTPUT topics. The test will consume directly from Kafka via consume_latest()
            # which works regardless of listener subscription.
            
            # Poll messages (use cache if available, otherwise poll Kafka directly)
            received_messages = []
            all_received_messages = []  # Track ALL messages for logging/closest match
            seen_message_keys = set()  # Track seen messages to avoid duplicates from cache
            end_time = time.time() + (expectation.wait_ms / 1000.0)
            last_cache_check_time = time.time()

            while time.time() < end_time:
                # Use cache if available, otherwise fall back to Kafka polling
                if self.message_cache:
                    # Get messages from cache received since we started waiting
                    cached_msgs = self.message_cache.get_messages(expectation.topic, since=start_time)
                    messages = [
                        {
                            "value": m.value,
                            "timestamp": m.timestamp,
                            "partition": m.partition,
                            "offset": m.offset,
                            "headers": m.headers
                        }
                        for m in cached_msgs
                    ]
                    logger.debug(f"Got {len(messages)} messages from cache for topic {expectation.topic}")
                else:
                    # Fall back to polling Kafka directly
                    messages = self.kafka_client.consume_latest(
                        topic=expectation.topic,
                        max_messages=100,
                        timeout_ms=500,
                        poll_interval_ms=100
                    )

                for msg in messages:
                    if "error" in msg:
                        continue

                    # Create unique key for deduplication (partition + offset uniquely identifies a message)
                    msg_key = (msg.get("partition", 0), msg.get("offset", 0))
                    if msg_key in seen_message_keys:
                        logger.debug(f"Skipping duplicate message: partition={msg_key[0]}, offset={msg_key[1]}")
                        continue
                    seen_message_keys.add(msg_key)

                    # Filter messages to only those received after test start
                    # Message timestamp is in milliseconds, test_start_time is in seconds
                    if test_start_time is not None:
                        msg_timestamp_seconds = msg.get("timestamp", 0) / 1000.0
                        if msg_timestamp_seconds < test_start_time:
                            logger.debug(f"Skipping message received before test start: {msg_timestamp_seconds} < {test_start_time}")
                            continue

                    try:
                        msg_value = msg.get("value")
                        if isinstance(msg_value, str):
                            try:
                                msg_value = json.loads(msg_value)
                            except json.JSONDecodeError:
                                pass
                    except Exception as e:
                        logger.debug(f"Failed to parse message value: {e}")
                        continue

                    # Track this message for logging and closest match analysis
                    msg_for_logging = ReceivedMessage(
                        value=msg_value,
                        timestamp=msg.get("timestamp", 0),
                        partition=msg.get("partition", 0),
                        offset=msg.get("offset", 0),
                        headers=msg.get("headers")
                    )

                    # Check correlation and conditions
                    correlation_matched = False
                    conditions_matched = 0

                    # Check correlation target if specified
                    if expectation.correlate and expectation.correlate.target and correlation_value is not None:
                        try:
                            target = expectation.correlate.target
                            target_value = None
                            if "jsonpath" in target:
                                expr_str = target["jsonpath"]
                                target_expr = jsonpath_parse(expr_str)
                                matches = target_expr.find(msg_value)
                                target_value = matches[0].value if matches else None
                            elif "header" in target:
                                header_name = target["header"]
                                headers = msg.get("headers", {})
                                target_value = headers.get(header_name)
                            
                            if target_value != correlation_value:
                                # Log this non-matching message for debugging
                                if test_logger:
                                    test_logger.log_received_message(
                                        topic=expectation.topic,
                                        payload=msg_value,
                                        correlation_matched=False,
                                        conditions_matched=0,
                                        total_conditions=len(expectation.match) if expectation.match else 0,
                                        headers=msg.get("headers")
                                    )
                                all_received_messages.append(msg_for_logging)
                                continue
                            correlation_matched = True
                        except Exception as e:
                            logger.warning(f"Failed to extract/match target correlation: {e}")
                            if test_logger:
                                test_logger.log_received_message(
                                    topic=expectation.topic,
                                    payload=msg_value,
                                    correlation_matched=False,
                                    conditions_matched=0,
                                    total_conditions=len(expectation.match) if expectation.match else 0,
                                    headers=msg.get("headers")
                                )
                            all_received_messages.append(msg_for_logging)
                            continue
                    elif not expectation.correlate or not expectation.correlate.target:
                        # No correlation matching needed
                        correlation_matched = True

                    # Check conditions
                    if expectation.match:
                        conditions_matched = 0
                        for condition in expectation.match:
                            try:
                                matcher = self.matcher_factory.create(condition.type)

                                # Build matcher-specific condition dict (same as _match_conditions)
                                if condition.type == 'jsonpath':
                                    # JSONPathMatcher expects {'path', 'value', 'regex'}
                                    matcher_condition = {
                                        'path': condition.expression,
                                        'value': condition.value,
                                        'regex': condition.regex
                                    }
                                else:
                                    # Other matchers work with the condition object directly
                                    matcher_condition = condition

                                if matcher and matcher.match(msg_value, matcher_condition).matched:
                                    conditions_matched += 1
                            except Exception as e:
                                logger.debug(f"Error matching condition: {e}")
                                pass

                        if conditions_matched < len(expectation.match):
                            # Log this non-matching message for debugging
                            if test_logger:
                                test_logger.log_received_message(
                                    topic=expectation.topic,
                                    payload=msg_value,
                                    correlation_matched=correlation_matched,
                                    conditions_matched=conditions_matched,
                                    total_conditions=len(expectation.match),
                                    headers=msg.get("headers")
                                )
                            all_received_messages.append(msg_for_logging)
                            continue

                    # Message matches all conditions!
                    received_messages.append(msg_for_logging)
                    all_received_messages.append(msg_for_logging)

                    # Always log matching message
                    if test_logger:
                        test_logger.log_received_message(
                            topic=expectation.topic,
                            payload=msg_value,
                            correlation_matched=correlation_matched,
                            conditions_matched=conditions_matched,
                            total_conditions=len(expectation.match) if expectation.match else 0,
                            headers=msg.get("headers")
                        )

                if received_messages:
                    break

                await asyncio.sleep(0.1)

            exp_result.received = len(received_messages)
            exp_result.received_messages = [asdict(m) for m in received_messages]
            exp_result.status = "MATCHED" if received_messages else "TIMEOUT"

        except Exception as e:
            logger.error(f"Failed to collect expectation messages: {e}")
            exp_result.status = "NO_MATCH"
            exp_result.error = str(e)

        exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
        return exp_result

    def _match_conditions(self, message: Any, conditions: List) -> bool:
        """Check if message matches all conditions (AND logic)."""
        if not conditions:
            return True

        for condition in conditions:
            try:
                matcher = self.matcher_factory.create(condition.type)
                if not matcher:
                    logger.warning(f"Unknown matcher type: {condition.type}")
                    return False

                # Build matcher-specific condition dict
                if condition.type == 'jsonpath':
                    # JSONPathMatcher expects {'path', 'value', 'regex'}
                    matcher_condition = {
                        'path': condition.expression,
                        'value': condition.value,
                        'regex': condition.regex
                    }
                else:
                    # Other matchers work with the condition object directly
                    matcher_condition = condition

                result = matcher.match(message, matcher_condition)
                if not result.matched:
                    return False
            except Exception as e:
                logger.warning(f"Error matching condition {condition.type}: {e}")
                return False

        return True


class TestSuiteRunner:
    """Orchestrates running multiple tests sequentially or in parallel."""

    def __init__(
        self,
        kafka_client: KafkaClientWrapper,
        custom_placeholder_registry: Optional[CustomPlaceholderRegistry] = None,
        test_suite_dir: str = "/testSuite",
        message_cache = None,
        listener_engine = None
    ):
        """Initialize test suite runner."""
        self.kafka_client = kafka_client
        self.custom_placeholder_registry = custom_placeholder_registry
        self.test_suite_dir = test_suite_dir
        self.executor = TestExecutor(
            kafka_client,
            custom_placeholder_registry,
            test_suite_dir,
            message_cache=message_cache,
            listener_engine=listener_engine
        )

    async def run_tests_sequential(self, tests: List[TestDefinition], verbose: bool = False) -> List[TestResult]:
        """Run tests sequentially."""
        results = []
        for test in tests:
            # Use file_path from test definition
            test_file_path = Path(test.file_path) if test.file_path else None
            result = await self.executor.run_test(test, test_file_path, verbose=verbose)
            results.append(result)
            logger.info(f"Test {test.name}: {result.status}")
        return results

    async def run_tests_parallel(
        self,
        tests: List[TestDefinition],
        threads: int = 4,
        verbose: bool = False
    ) -> List[TestResult]:
        """Run tests in parallel using thread pool."""
        results = []
        with ThreadPoolExecutor(max_workers=threads) as executor:
            loop = asyncio.get_event_loop()
            futures = [
                loop.run_in_executor(
                    executor,
                    lambda t=test: asyncio.run(
                        self.executor.run_test(t, Path(t.file_path) if t.file_path else None, verbose=verbose)
                    )
                )
                for test in tests
            ]
            for future in as_completed(futures):
                try:
                    result = await future
                    results.append(result)
                    logger.info(f"Test {result.test_id}: {result.status}")
                except Exception as e:
                    logger.error(f"Parallel test execution failed: {e}")
        return results


class TestResultAggregator:
    """Aggregates test results for reporting."""

    @staticmethod
    def aggregate_results(
        results: List[TestResult],
        mode: str = "sequential"
    ) -> Dict[str, Any]:
        """Aggregate test results into summary."""
        total = len(results)
        passed = sum(1 for r in results if r.status == "PASSED")
        failed = sum(1 for r in results if r.status == "FAILED")
        skipped = sum(1 for r in results if r.status == "SKIPPED")
        total_elapsed = sum(r.elapsed_ms for r in results)

        # Group by test name for stats
        stats_by_test = {}
        for result in results:
            if result.test_id not in stats_by_test:
                stats_by_test[result.test_id] = {
                    "passed": 0,
                    "failed": 0,
                    "elapsed_times": []
                }
            if result.status == "PASSED":
                stats_by_test[result.test_id]["passed"] += 1
            elif result.status == "FAILED":
                stats_by_test[result.test_id]["failed"] += 1
            stats_by_test[result.test_id]["elapsed_times"].append(result.elapsed_ms)

        # Calculate per-test stats
        stats = {}
        for test_id, test_stats in stats_by_test.items():
            times = test_stats["elapsed_times"]
            stats[test_id] = {
                "passed": test_stats["passed"],
                "failed": test_stats["failed"],
                "elapsed_ms_avg": sum(times) / len(times) if times else 0,
                "elapsed_ms_max": max(times) if times else 0,
                "elapsed_ms_min": min(times) if times else 0
            }

        # Collect failed test details
        failed_tests = [
            {
                "test_id": r.test_id,
                "error": "; ".join(r.errors),
                "elapsed_ms": r.elapsed_ms
            }
            for r in results if r.status == "FAILED"
        ]

        return {
            "mode": mode,
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration_ms": total_elapsed,
            "stats": stats,
            "failed_tests": failed_tests
        }

