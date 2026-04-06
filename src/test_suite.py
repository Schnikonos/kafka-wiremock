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
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JSONPathError

from .test_loader import TestDefinition, TestInjection, TestExpectation, TestScript
from .kafka_client import KafkaClientWrapper
from .matcher import MatcherFactory
from .templater import TemplateRenderer
from .custom_placeholders import CustomPlaceholderRegistry

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
        test_suite_dir: str = "/testSuite"
    ):
        """Initialize test executor."""
        self.kafka_client = kafka_client
        self.custom_placeholder_registry = custom_placeholder_registry or CustomPlaceholderRegistry()
        self.matcher_factory = MatcherFactory()
        self.test_suite_dir = test_suite_dir

    async def run_test(self, test: TestDefinition) -> TestResult:
        """Execute a single test."""
        start_time = time.time()
        result = TestResult(test_id=test.name)

        try:
            if test.skip:
                result.status = "SKIPPED"
                result.elapsed_ms = int((time.time() - start_time) * 1000)
                return result

            # Phase 1: Execute "when"
            when_result = await self._execute_when(test)
            result.when_result = when_result

            if when_result.script_error:
                result.status = "FAILED"
                result.errors.append(f"When phase failed: {when_result.script_error}")
                result.elapsed_ms = int((time.time() - start_time) * 1000)
                return result

            # Phase 2: Execute "then"
            then_result = await self._execute_then(test, result.when_result)
            result.then_result = then_result

            if then_result.script_error:
                result.status = "FAILED"
                result.errors.append(f"Then phase failed: {then_result.script_error}")
                result.elapsed_ms = int((time.time() - start_time) * 1000)
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
        return result

    async def _execute_when(self, test: TestDefinition) -> WhenResult:
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
                            "now": datetime.utcnow().isoformat() + "Z",
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
                {"message_id": m.message_id, "topic": m.topic, "status": m.status}
                for m in injected_messages
            ]

        except Exception as e:
            logger.error(f"When phase failed: {e}")
            result.script_error = str(e)

        return result

    async def _execute_then(self, test: TestDefinition, when_result: WhenResult) -> ThenResult:
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
                        item, len(collected_results), when_result, injections_dict, context
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
        context: Dict[str, Any]
    ) -> ExpectationResult:
        """Collect messages for a single expectation with correlation."""
        exp_result = ExpectationResult(
            index=exp_idx,
            topic=expectation.topic,
            expected=1,
            received=0
        )

        start_time = time.time()

        try:
            # Resolve correlation if message_id specified
            correlation_value = None
            if expectation.message_id and expectation.source_id:
                # Extract field from injected message
                injected_data = injections_dict.get(expectation.message_id)
                if injected_data:
                    # Need to access the full payload - for now match on message_id itself
                    correlation_value = expectation.message_id
                else:
                    exp_result.error = f"Message not found: {expectation.message_id}"
                    exp_result.status = "NO_MATCH"
                    exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                    return exp_result

            # Poll messages
            received_messages = []
            end_time = time.time() + (expectation.wait_ms / 1000.0)

            while time.time() < end_time:
                messages = self.kafka_client.consume_latest(
                    topic=expectation.topic,
                    max_messages=100,
                    timeout_ms=500,
                    poll_interval_ms=100
                )

                for msg in messages:
                    if "error" in msg:
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

                    # Check correlation and conditions
                    if expectation.message_id and expectation.source_id and expectation.target_id:
                        # Extract target value
                        try:
                            target_expr = jsonpath_parse(expectation.target_id)
                            matches = target_expr.find(msg_value)
                            target_value = matches[0].value if matches else None
                        except Exception:
                            target_value = None

                        if target_value != correlation_value:
                            continue

                    # Check conditions
                    if expectation.match:
                        if not self._match_conditions(msg_value, expectation.match):
                            continue

                    # Message matches!
                    received_msg = ReceivedMessage(
                        value=msg_value,
                        timestamp=msg.get("timestamp", 0),
                        partition=msg.get("partition", 0),
                        offset=msg.get("offset", 0),
                        headers=msg.get("headers")
                    )
                    received_messages.append(received_msg)

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
            matcher = self.matcher_factory.get_matcher(condition.type)
            if not matcher:
                logger.warning(f"Unknown matcher type: {condition.type}")
                return False

            result = matcher.match(message, condition)
            if not result.matched:
                return False

        return True


class TestSuiteRunner:
    """Orchestrates running multiple tests sequentially or in parallel."""

    def __init__(
        self,
        kafka_client: KafkaClientWrapper,
        custom_placeholder_registry: Optional[CustomPlaceholderRegistry] = None,
        test_suite_dir: str = "/testSuite"
    ):
        """Initialize test suite runner."""
        self.kafka_client = kafka_client
        self.custom_placeholder_registry = custom_placeholder_registry
        self.test_suite_dir = test_suite_dir
        self.executor = TestExecutor(kafka_client, custom_placeholder_registry, test_suite_dir)

    async def run_tests_sequential(self, tests: List[TestDefinition]) -> List[TestResult]:
        """Run tests sequentially."""
        results = []
        for test in tests:
            result = await self.executor.run_test(test)
            results.append(result)
            logger.info(f"Test {test.name}: {result.status}")
        return results

    async def run_tests_parallel(
        self,
        tests: List[TestDefinition],
        threads: int = 4
    ) -> List[TestResult]:
        """Run tests in parallel using thread pool."""
        results = []
        with ThreadPoolExecutor(max_workers=threads) as executor:
            loop = asyncio.get_event_loop()
            futures = [
                loop.run_in_executor(executor, lambda t=test: asyncio.run(self.executor.run_test(t)))
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

