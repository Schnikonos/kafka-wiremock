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

from .loader import TestDefinition, TestInjection, TestExpectation, TestScript, HttpInjectionResult, TestDBAction
from ..kafka.client import KafkaClientWrapper
from ..rules.matcher import MatcherFactory
from ..rules.templater import TemplateRenderer
from ..custom.placeholders import CustomPlaceholderRegistry
from ..fault.injector import FaultInjector
from .logger import TestLogger
# Import HttpExecutor and HttpStubCache lazily to avoid circular imports
# (src/http/__init__.py → executor → test/loader → test/__init__ → suite → http/__init__)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..http.executor import HttpExecutor
    from ..http.stub_cache import HttpStub, HttpStubCache
    from ..db.executor import DBExecutor
logger = logging.getLogger(__name__)


def _vtest(verbose: bool, msg: str) -> None:
    """Emit a verbose test log line when verbose mode is active."""
    if verbose:
        logger.info(f"[VERBOSE-TESTS] {msg}")


def _extract_actual_value(condition_type: str, expression, msg_value, msg: dict) -> str:
    """
    Extract the actual value from a message for verbose condition logging.
    Mirrors the 'actual=' field that matchers emit in [VERBOSE-RULES] lines.
    """
    try:
        if condition_type == 'jsonpath' and expression:
            from jsonpath_ng import parse as _jp_parse
            matches = _jp_parse(expression).find(msg_value)
            return repr(matches[0].value) if matches else "<not found>"
        elif condition_type == 'header' and expression:
            headers = msg.get('headers') or {}
            v = headers.get(expression)
            return repr(v) if v is not None else "<not found>"
        elif condition_type == 'key':
            k = msg.get('key')
            return repr(k) if k is not None else "<no key>"
        else:
            # exact / partial / regex — show first 120 chars of stringified message
            return repr(str(msg_value)[:120])
    except Exception as e:
        return f"<error: {e}>"


def _format_condition_vtest(
    exp_idx: int,
    topic: str,
    idx: int,
    condition,
    matched: bool,
    msg_value,
    msg: dict,
) -> str:
    """
    Build a single verbose test log line for one condition evaluation.

    Format mirrors [VERBOSE-RULES] matcher output, e.g.:
      topic='out' [expectation #0] condition #0 (jsonpath) path='$.status' expected='ACTIVE' actual='INACTIVE' → ✗ NO MATCH
      topic='out' [expectation #0] condition #1 (header) header='X-Corr-Id' expected='abc' actual='xyz' → ✓ MATCH
    """
    ctype = getattr(condition, 'type', '?')
    expression = getattr(condition, 'expression', None)
    value = getattr(condition, 'value', None)
    regex = getattr(condition, 'regex', None)
    icon = "✓ MATCH" if matched else "✗ NO MATCH"

    prefix = f"topic={topic!r} [expectation #{exp_idx}] condition #{idx} ({ctype})"
    parts = [prefix]

    if ctype == 'jsonpath':
        parts.append(f"path={expression!r}")
        if value is not None:
            parts.append(f"expected={value!r}")
        if regex:
            parts.append(f"regex={regex!r}")
        parts.append(f"actual={_extract_actual_value(ctype, expression, msg_value, msg)}")
    elif ctype == 'header':
        parts.append(f"header={expression!r}")
        if value is not None:
            parts.append(f"expected={value!r}")
        if regex:
            parts.append(f"regex={regex!r}")
        parts.append(f"actual={_extract_actual_value(ctype, expression, msg_value, msg)}")
    elif ctype == 'key':
        if value is not None:
            parts.append(f"expected={value!r}")
        if regex:
            parts.append(f"regex={regex!r}")
        parts.append(f"actual={_extract_actual_value(ctype, expression, msg_value, msg)}")
    else:
        # exact / partial / regex
        if value is not None:
            parts.append(f"expected={value!r}")
        if regex:
            parts.append(f"pattern={regex!r}")
        parts.append(f"actual={_extract_actual_value(ctype, expression, msg_value, msg)}")

    parts.append(f"→ {icon}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

# In 2026 Unix seconds ≈ 1.78 × 10⁹.  Unix milliseconds ≈ 1.78 × 10¹².
# Any value ≥ 10¹¹ is almost certainly milliseconds; anything below is seconds.
_MS_THRESHOLD = 1e11


def _to_seconds(ts: float) -> float:
    """Normalise a timestamp to seconds regardless of whether it was supplied
    in seconds or milliseconds."""
    if ts is None:
        return 0.0
    return float(ts) / 1000.0 if float(ts) >= _MS_THRESHOLD else float(ts)


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
    key: Optional[str] = None  # Message key from Kafka


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
    http_results: Dict[str, Any] = field(default_factory=dict)  # message_id → HttpInjectionResult
    context: Dict[str, Any] = field(default_factory=dict)       # accumulated DB/script context for use in 'then' phase


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
        listener_engine = None,
        jms_registry = None,  # Optional JMS registry for JMS injection/expectation support
        http_executor: Optional["HttpExecutor"] = None,  # Optional HTTP executor for HTTP requests
        stub_cache: Optional["HttpStubCache"] = None,  # Optional HTTP stub cache for http-stub expectations
        db_executor: Optional["DBExecutor"] = None,     # Optional DB executor for type=db actions
        topic_config_loader = None,   # Optional TopicConfigLoader for auto correlation
        jms_config_loader = None,     # Optional JMSConfigLoader for auto correlation
    ):
        """Initialize test executor."""
        self.kafka_client = kafka_client
        self.custom_placeholder_registry = custom_placeholder_registry or CustomPlaceholderRegistry()
        self.matcher_factory = MatcherFactory()
        self.test_suite_dir = test_suite_dir
        self.message_cache = message_cache
        self.listener_engine = listener_engine
        self.jms_registry = jms_registry
        self.http_executor = http_executor  # Optional; HTTP calls skipped if None
        self.stub_cache = stub_cache        # Optional; http-stub expectations skipped if None
        self.db_executor = db_executor      # Optional; DB actions skipped if None
        self.topic_config_loader = topic_config_loader  # Optional; correlation skipped if None
        self.jms_config_loader = jms_config_loader      # Optional; correlation skipped if None

    def _get_corr_config(self, destination: str, msg_type: str):
        """
        Return a CorrelationConfig for a destination (topic or JMS queue), or None.

        Picks the correct loader based on msg_type.
        Returns a CorrelationConfig dataclass (or None if not configured).
        """
        try:
            if msg_type == "jms" and self.jms_config_loader:
                jms_cfg = self.jms_config_loader.get_config(destination)
                if jms_cfg and jms_cfg.correlation:
                    from ..messaging.correlation import _normalise_corr_config
                    return _normalise_corr_config(jms_cfg.correlation)
            elif msg_type == "kafka" and self.topic_config_loader:
                topic_cfg = self.topic_config_loader.get_topic_config(destination)
                if topic_cfg and topic_cfg.correlation:
                    return topic_cfg.correlation
        except Exception as e:
            logger.debug(f"_get_corr_config({destination!r}, {msg_type!r}) failed: {e}")
        return None

    async def run_test(self, test: TestDefinition, test_file_path: Optional[Path] = None, verbose: bool = False, force_run: bool = False) -> TestResult:
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
            if test.skip and not force_run:
                result.status = "SKIPPED"
                result.elapsed_ms = int((time.time() - start_time) * 1000)
                return result

            # Register HTTP stub expectations (type=http-stub) BEFORE injections fire
            # so the mock server can respond to any calls made during the when phase.
            if self.stub_cache:
                self._register_http_stubs(test)

            # Phase 1: Execute "when"
            when_result = await self._execute_when(test, test_logger, verbose=verbose)
            result.when_result = when_result

            if when_result.script_error:
                result.status = "FAILED"
                result.errors.append(f"When phase failed: {when_result.script_error}")
                result.elapsed_ms = int((time.time() - start_time) * 1000)
                if test_logger:
                    test_logger.write_log_file(test.name, result.status, result.elapsed_ms, result.errors)
                return result

            # Phase 2: Execute "then"
            then_result = await self._execute_then(test, result.when_result, test_logger, test_start_time=start_time, verbose=verbose)
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

        finally:
            # Always clean up HTTP stubs so they don't bleed into other tests
            if self.stub_cache:
                self.stub_cache.cleanup_test(test.name)

        result.elapsed_ms = int((time.time() - start_time) * 1000)

        # Write log file
        if test_logger:
            test_logger.write_log_file(test.name, result.status, result.elapsed_ms, result.errors)

        return result

    def _register_http_stubs(self, test: TestDefinition) -> None:
        """
        Scan test.then.items for type=http-stub expectations and register
        them in the stub cache so the mock server can respond before the
        when-phase injections even run.
        """
        import uuid as _uuid
        from ..http.stub_cache import HttpStub  # direct module import avoids circular
        from .loader import HttpStubResponse as _HttpStubResponse
        for item in test.then.items:
            if not isinstance(item, TestExpectation):
                continue
            if item.msg_type != "http-stub":
                continue
            if not item.path:
                logger.warning(
                    f"Test '{test.name}': http-stub expectation missing 'path' — skipping registration"
                )
                continue
            # Determine server name (required when multiple servers exist)
            server_name = item.server or ""
            resp = item.response or _HttpStubResponse()
            stub = HttpStub(
                stub_id=f"{test.name}_{_uuid.uuid4().hex[:8]}",
                test_id=test.name,
                server_name=server_name,
                path_pattern=item.path,
                method=item.method or "*",
                match_conditions=item.match or [],
                response_status=resp.status_code,
                response_payload=resp.payload,
                response_headers=dict(resp.headers or {}),
                response_content_type=resp.content_type,
                expected_times=item.times,
            )
            # Store stub_id back on the expectation so _collect_expectation_messages can find it
            item._stub_id = stub.stub_id  # type: ignore[attr-defined]
            self.stub_cache.register(test.name, stub)
            logger.debug(
                f"Registered HTTP stub '{stub.stub_id}' for test '{test.name}': "
                f"{stub.method} {stub.path_pattern}"
            )

    async def _execute_when(self, test: TestDefinition, test_logger: Optional[TestLogger] = None, verbose: bool = False) -> WhenResult:
        """Execute 'when' phase: injections and scripts, sequential."""
        result = WhenResult()
        injected_messages = []
        context = {}
        # Track whether we have already seeded the bare-field shorthand keys
        # ({{$.fieldName}} resolves to the first injection's payload fields).
        _first_injection_added = False

        # Build template context once, shared across all item types in the when phase
        template_context = {
            "testId": test.name,
            "uuid": str(__import__('uuid').uuid4()),
            "now": datetime.now(timezone.utc).isoformat() + "Z",
            "randomInt": lambda min_val=0, max_val=100: __import__('random').randint(min_val, max_val)
        }
        if self.custom_placeholder_registry:
            placeholders = self.custom_placeholder_registry.get_all_placeholders()
            for name, func in placeholders.items():
                try:
                    template_context[name] = func(template_context)
                except Exception as e:
                    logger.warning(f"Failed to execute custom placeholder {name}: {e}")

        try:
            # Process items sequentially
            for item in test.when.items:
                if isinstance(item, TestInjection):
                    try:
                        # Refresh dynamic placeholders and merge current context
                        template_context["uuid"] = str(__import__('uuid').uuid4())
                        template_context["now"] = datetime.now(timezone.utc).isoformat() + "Z"

                        template_context.update(context)

                        # Render and inject
                        rendered_payload = TemplateRenderer.render(item.payload, template_context) if item.payload else None
                        rendered_headers = None
                        if item.headers:
                            rendered_headers = {
                                k: TemplateRenderer.render(v, template_context)
                                for k, v in item.headers.items()
                            }

                        # Render key if present
                        rendered_key = None
                        if item.key:
                            rendered_key = TemplateRenderer.render(item.key, template_context)

                        try:
                            payload_obj = json.loads(rendered_payload) if rendered_payload else None
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

                        # Apply messageKey poison pill if configured
                        if item.fault and item.fault.poison_pill > 0 and 'messageKey' in item.fault.poison_pill_type:
                            if FaultInjector._should_fault(item.fault.poison_pill):
                                rendered_key = FaultInjector.apply_messagekey_poison_pill(rendered_key)

                        # Auto-inject correlation ID if not explicitly set and
                        # the destination has correlation extract rules configured.
                        if not item.correlation_id and item.msg_type in ("kafka", "jms"):
                            try:
                                _corr_cfg = self._get_corr_config(item.destination, item.msg_type)
                                if _corr_cfg and _corr_cfg.extract:
                                    import uuid as _uuid_mod
                                    auto_corr_id = str(_uuid_mod.uuid4())
                                    # Inject into headers via apply_propagation helper
                                    from ..messaging.correlation import apply_propagation as _apply_prop
                                    rendered_headers = _apply_prop(
                                        rendered_headers, auto_corr_id, _corr_cfg
                                    )
                                    # For jsonpath extract rules, also set the field in the payload
                                    if isinstance(payload_obj, dict):
                                        for _r in _corr_cfg.extract:
                                            if getattr(_r, 'from_type', None) == 'jsonpath' and _r.expression:
                                                _path = _r.expression.lstrip('$').lstrip('.')
                                                if _path and '.' not in _path:
                                                    payload_obj[_path] = auto_corr_id
                                    # Store effective correlation ID for expectation phase
                                    context[f"inject.{item.message_id}._correlation_id"] = auto_corr_id
                                    template_context[f"inject.{item.message_id}._correlation_id"] = auto_corr_id
                                    logger.debug(
                                        f"Auto-injected correlationId={auto_corr_id!r} "
                                        f"for message_id={item.message_id!r}"
                                    )
                            except Exception as _auto_corr_err:
                                logger.debug(f"Auto-inject correlation skipped: {_auto_corr_err}")

                        # Route to appropriate client based on message type
                        if item.msg_type == "http":
                            if not self.http_executor:
                                raise Exception(f"HTTP executor not initialized, cannot call {item.destination}")
                            rendered_url = TemplateRenderer.render(item.destination, template_context)
                            rendered_query = None
                            if item.query_params:
                                rendered_query = {k: TemplateRenderer.render(v, template_context) for k, v in item.query_params.items()}
                            http_result = await self.http_executor.execute(
                                url=rendered_url,
                                method=item.method,
                                payload=rendered_payload if item.payload else None,
                                headers=rendered_headers,
                                query_params=rendered_query,
                                auth_ref=item.auth_ref,
                                tls_ref=item.tls_ref,
                                timeout_ms=item.http_timeout_ms,
                                message_id=item.message_id,
                            )
                            # Store HTTP result for use in then-phase expectations
                            result.http_results[item.message_id] = http_result
                            logger.info(f"HTTP {item.method} {rendered_url} → {http_result.status_code} (message_id={item.message_id})")
                        elif item.msg_type == "jms":
                            if not self.jms_registry or self.jms_registry.is_empty():
                                raise Exception(f"JMS client not initialized, cannot inject to {item.destination}")
                            jms_client = self.jms_registry.get_client(item.connection_ref)
                            jms_client.put_message(
                                destination=item.destination,
                                payload=json.dumps(payload_obj) if isinstance(payload_obj, dict) else str(payload_obj),
                                headers=rendered_headers,
                            )
                        else:
                            self.kafka_client.produce(
                                topic=item.destination,
                                message=payload_obj,
                                headers=rendered_headers,
                                key=rendered_key
                            )

                        # Handle message duplication if configured (not for HTTP)
                        if item.msg_type != "http" and item.fault and FaultInjector.should_duplicate(item.fault):
                            logger.info(f"Duplicating test injection message to {item.destination} (fault injection)")
                            if item.msg_type == "jms":
                                jms_client = self.jms_registry.get_client(item.connection_ref)
                                jms_client.put_message(
                                    destination=item.destination,
                                    payload=json.dumps(payload_obj) if isinstance(payload_obj, dict) else str(payload_obj),
                                    headers=rendered_headers,
                                )
                            else:
                                self.kafka_client.produce(
                                    topic=item.destination,
                                    message=payload_obj,
                                    headers=rendered_headers,
                                    key=rendered_key
                                )

                        injected_msg = InjectedMessage(
                            message_id=item.message_id,
                            topic=item.destination,
                            payload=payload_obj,
                            headers=rendered_headers,
                            timestamp=int(time.time() * 1000),
                            status="ok"
                        )
                        injected_messages.append(injected_msg)

                        # Expose this injection's payload fields in the shared template
                        # context so later injections (and the then-phase) can reference
                        # them via {{inject.<message_id>.<field>}}.
                        # The first injection's fields are also added as bare keys so that
                        # {{$.fieldName}} resolves to the first injection's payload.
                        if isinstance(payload_obj, dict):
                            for _f, _v in payload_obj.items():
                                template_context[f"inject.{item.message_id}.{_f}"] = _v
                            if not _first_injection_added:
                                for _f, _v in payload_obj.items():
                                    template_context[_f] = _v
                                _first_injection_added = True

                        # Track if this injection had fault with check_result=False
                        if item.fault and not item.fault.check_result:
                            result.faulted_injections.append(item.message_id)
                            logger.info(f"Marked injection {item.message_id} as faulted (check_result=False)")

                        # Log sent message
                        if test_logger:
                            test_logger.log_sent_message(
                                topic=item.destination,
                                payload=payload_obj,
                                message_id=item.message_id,
                                headers=rendered_headers,
                                key=rendered_key
                            )

                        _vtest(verbose, (
                            f"test={test.name!r} INJECT→ destination={item.destination!r} type={item.msg_type!r} "
                            f"message_id={item.message_id!r} key={rendered_key!r} "
                            f"headers={rendered_headers} payload={json.dumps(payload_obj, default=str)[:500]}"
                        ))

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

                elif isinstance(item, TestDBAction):
                    # Execute DB action (insert/update/delete/select for test data setup)
                    if self.db_executor is None:
                        logger.warning(
                            f"test={test.name!r} DB action '{item.id}' skipped: "
                            f"no db_registry configured"
                        )
                        continue
                    try:
                        if item.delay_ms > 0:
                            await asyncio.sleep(item.delay_ms / 1000.0)
                        # Render query and params with current template context
                        rendered_query = TemplateRenderer.render(item.query, template_context)
                        rendered_params: Optional[Dict[str, Any]] = None
                        if item.params:
                            rendered_params = {
                                k: TemplateRenderer.render(str(v), template_context)
                                for k, v in item.params.items()
                            }
                        db_context = self.db_executor.execute(
                            db_ref=item.db_ref,
                            operation=item.operation,
                            query=rendered_query,
                            params=rendered_params,
                            step_id=item.id,
                        )
                        context.update(db_context)
                        template_context.update(db_context)
                        if test_logger:
                            test_logger.log_db_action(
                                phase="when",
                                step_id=item.id,
                                db_ref=item.db_ref,
                                operation=item.operation,
                                db_context=db_context,
                                query=rendered_query,
                                params=rendered_params,
                            )
                        _pfx = f"db.{item.id}"
                        _summary_parts = []
                        if db_context.get(f"{_pfx}.rows_affected") is not None:
                            _summary_parts.append(f"rows_affected={db_context[f'{_pfx}.rows_affected']}")
                        if db_context.get(f"{_pfx}.row_count") is not None:
                            _summary_parts.append(f"row_count={db_context[f'{_pfx}.row_count']}")
                        if db_context.get(f"{_pfx}.generated_key") is not None:
                            _summary_parts.append(f"generated_key={db_context[f'{_pfx}.generated_key']!r}")
                        _result_summary = " → " + ", ".join(_summary_parts) if _summary_parts else f" → context keys: {list(db_context.keys())}"
                        logger.info(
                            f"test={test.name!r} DB {item.operation} step='{item.id}' "
                            f"db='{item.db_ref}'{_result_summary}"
                        )
                        _rows_val = db_context.get(f"{_pfx}.rows")
                        _vtest(verbose, (
                            f"test={test.name!r} DB-ACTION step='{item.id}' "
                            f"db='{item.db_ref}' operation='{item.operation}' "
                            f"query={rendered_query!r}"
                            + (f" params={rendered_params!r}" if rendered_params else "")
                            + (f" rows={_rows_val!r}" if _rows_val is not None else f" context={list(db_context.keys())}")
                        ))
                    except Exception as e:
                        logger.error(
                            f"test={test.name!r} DB action '{item.id}' failed: {e}"
                        )
                        result.script_error = str(e)
                        break

            result.injected = [
                {"message_id": m.message_id, "topic": m.topic, "status": m.status,
                 "payload": m.payload, "headers": m.headers}
                for m in injected_messages
            ]
            result.context = context

        except Exception as e:
            logger.error(f"When phase failed: {e}")
            result.script_error = str(e)

        return result

    async def _execute_then(self, test: TestDefinition, when_result: WhenResult, test_logger: Optional[TestLogger] = None, test_start_time: float = None, verbose: bool = False) -> ThenResult:
        """Execute 'then' phase: expectations and scripts, sequential."""
        result = ThenResult()
        context = dict(when_result.context)  # seed with DB/script context from 'when' phase
        collected_results = []

        try:
            # Build injections dict for correlation
            injections_dict = {m["message_id"]: m for m in when_result.injected}

            # Process items sequentially
            for item in test.then.items:
                if isinstance(item, TestExpectation):
                    # Collect expectation messages
                    exp_result = await self._collect_expectation_messages(
                        item, len(collected_results), when_result, injections_dict, context,
                        test_logger, test_start_time=test_start_time, verbose=verbose,
                        test_id=test.name
                    )
                    result.expectations.append(exp_result)
                    collected_results.append(exp_result)

                    # If this expectation has a message_id and matched successfully,
                    # expose the first matched message's payload as
                    # {{expect.<message_id>.<field>}} for use in subsequent items.
                    if item.message_id and exp_result.status == "MATCHED" and exp_result.received_messages:
                        _matched_msg = exp_result.received_messages[0]
                        _matched_val = _matched_msg.get("value")
                        if isinstance(_matched_val, dict):
                            for _ef, _ev in _matched_val.items():
                                context[f"expect.{item.message_id}.{_ef}"] = _ev
                        # Also expose message key and headers under reserved names
                        _mk = _matched_msg.get("key")
                        if _mk is not None:
                            context[f"expect.{item.message_id}._key"] = _mk
                        _hdrs = _matched_msg.get("headers") or {}
                        for _hk, _hv in _hdrs.items():
                            context[f"expect.{item.message_id}._header.{_hk}"] = _hv

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

                elif isinstance(item, TestDBAction):
                    # Execute DB action (cleanup, assertion, etc.)
                    if self.db_executor is None:
                        logger.warning(
                            f"test={test.name!r} DB action '{item.id}' skipped: "
                            f"no db_registry configured"
                        )
                        continue
                    try:
                        if item.delay_ms > 0:
                            await asyncio.sleep(item.delay_ms / 1000.0)
                        # Build template context from accumlated when/then context
                        template_ctx = dict(context)
                        rendered_query = TemplateRenderer.render(item.query, template_ctx)
                        rendered_params: Optional[Dict[str, Any]] = None
                        if item.params:
                            rendered_params = {
                                k: TemplateRenderer.render(str(v), template_ctx)
                                for k, v in item.params.items()
                            }
                        db_context = self.db_executor.execute(
                            db_ref=item.db_ref,
                            operation=item.operation,
                            query=rendered_query,
                            params=rendered_params,
                            step_id=item.id,
                        )
                        context.update(db_context)

                        # For select: optionally validate row count and match conditions
                        exp_result = self._evaluate_db_assertion(item, db_context, len(collected_results))
                        if exp_result is not None:
                            result.expectations.append(exp_result)
                            collected_results.append(exp_result)

                        if test_logger:
                            test_logger.log_db_action(
                                phase="then",
                                step_id=item.id,
                                db_ref=item.db_ref,
                                operation=item.operation,
                                db_context=db_context,
                                query=rendered_query,
                                params=rendered_params,
                            )
                        _pfx = f"db.{item.id}"
                        _summary_parts = []
                        if db_context.get(f"{_pfx}.rows_affected") is not None:
                            _summary_parts.append(f"rows_affected={db_context[f'{_pfx}.rows_affected']}")
                        if db_context.get(f"{_pfx}.row_count") is not None:
                            _summary_parts.append(f"row_count={db_context[f'{_pfx}.row_count']}")
                        if db_context.get(f"{_pfx}.generated_key") is not None:
                            _summary_parts.append(f"generated_key={db_context[f'{_pfx}.generated_key']!r}")
                        _result_summary = " → " + ", ".join(_summary_parts) if _summary_parts else f" → context keys: {list(db_context.keys())}"
                        logger.info(
                            f"test={test.name!r} DB {item.operation} step='{item.id}' "
                            f"db='{item.db_ref}'{_result_summary}"
                        )
                        _rows_val = db_context.get(f"{_pfx}.rows")
                        _vtest(verbose, (
                            f"test={test.name!r} DB-ACTION step='{item.id}' "
                            f"db='{item.db_ref}' operation='{item.operation}' "
                            f"query={rendered_query!r}"
                            + (f" params={rendered_params!r}" if rendered_params else "")
                            + (f" rows={_rows_val!r}" if _rows_val is not None else f" context={list(db_context.keys())}")
                        ))
                    except Exception as e:
                        logger.error(
                            f"test={test.name!r} DB action '{item.id}' failed: {e}"
                        )
                        result.script_error = str(e)
                        break

        except Exception as e:
            logger.error(f"Then phase failed: {e}")
            result.script_error = str(e)

        return result

    def _evaluate_db_assertion(
        self,
        item: TestDBAction,
        db_context: Dict[str, Any],
        exp_idx: int,
    ) -> Optional[ExpectationResult]:
        """
        Evaluate optional assertion conditions on a DB action result (then phase).

        Returns an ExpectationResult if the action has match conditions or
        expected_row_count set; None otherwise (pure side-effect, no assertion).
        """
        has_assertion = bool(item.match) or item.expected_row_count is not None
        if not has_assertion:
            return None

        prefix = f"db.{item.id}"
        row_count = db_context.get(f"{prefix}.row_count", db_context.get(f"{prefix}.rows_affected", 0))
        rows = db_context.get(f"{prefix}.rows", [])
        first_row = rows[0] if rows else {}

        errors: List[str] = []

        # Row count assertion
        if item.expected_row_count is not None:
            if row_count != item.expected_row_count:
                errors.append(
                    f"DB assertion '{item.id}': expected {item.expected_row_count} row(s), "
                    f"got {row_count}"
                )

        # Match condition assertions (applied to first row as a dict)
        for cond in item.match:
            try:
                matcher = self.matcher_factory.create(cond.type)
                if cond.type == "jsonpath":
                    match_condition = {
                        "path": cond.expression,
                        "value": cond.value,
                        "regex": cond.regex,
                    }
                    match_result = matcher.match(first_row, match_condition)
                else:
                    mc = cond.regex if cond.regex else cond.value
                    match_result = matcher.match(first_row, mc)
                if not match_result.matched:
                    errors.append(
                        f"DB assertion '{item.id}': condition {cond.type} "
                        f"expression={cond.expression!r} expected={cond.value!r} → NO MATCH "
                        f"(actual row: {first_row})"
                    )
            except Exception as e:
                errors.append(f"DB assertion '{item.id}': condition evaluation error: {e}")

        status = "MATCHED" if not errors else "NO_MATCH"
        return ExpectationResult(
            index=exp_idx,
            topic=f"db:{item.db_ref}:{item.operation}",
            expected=1,
            received=1 if not errors else 0,
            status=status,
            error="; ".join(errors) if errors else None,
        )

    async def _collect_expectation_messages(
        self,
        expectation: TestExpectation,
        exp_idx: int,
        when_result: WhenResult,
        injections_dict: Dict[str, Any],
        context: Dict[str, Any],
        test_logger: Optional[TestLogger] = None,
        test_start_time: float = None,
        verbose: bool = False,
        test_id: str = "",
    ) -> ExpectationResult:
        """Collect messages for a single expectation with correlation."""

        # Build template context for rendering condition values in this expectation.
        # Priority (highest first): script context > injected payloads > testId / builtins.
        _template_ctx: Dict[str, Any] = {
            "testId": test_id,
        }
        # Add custom placeholder results (uuid/now/etc. are resolved on-demand by
        # TemplateRenderer itself via the global registry, no need to add them here)
        if self.custom_placeholder_registry:
            try:
                all_placeholders = self.custom_placeholder_registry.get_all_placeholders()
                for _ph_name, _ph_func in all_placeholders.items():
                    try:
                        _template_ctx[_ph_name] = _ph_func(_template_ctx)
                    except Exception:
                        pass
            except Exception:
                pass
        # Expose injected message payloads as inject.<message_id>.<field> flat keys.
        # The first injection's fields are also added as bare keys so that
        # {{$.fieldName}} resolves to the first injection's payload.
        _first_inj_added = False
        for _msg_id, _msg_data in injections_dict.items():
            _payload = _msg_data.get("payload")
            if isinstance(_payload, dict):
                for _field, _val in _payload.items():
                    _template_ctx[f"inject.{_msg_id}.{_field}"] = _val
                if not _first_inj_added:
                    for _field, _val in _payload.items():
                        _template_ctx[_field] = _val   # {{$.fieldName}} shorthand
                    _first_inj_added = True
        # Script-accumulated context values (including expect.<id>.<field> from
        # previously resolved expectations) override everything else.
        _template_ctx.update(context)

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
                        available_ids = sorted(injections_dict.keys())
                        _err = (
                            f"Correlation failed: message_id '{corr.message_id}' not found "
                            f"among injected messages {available_ids}"
                        )
                        logger.error(f"test expectation #{exp_idx}: {_err}")
                        exp_result.error = _err
                        exp_result.status = "NO_MATCH"
                        exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                        return exp_result
                elif corr.message_id:
                    # message_id without source/target — try to auto-derive correlation
                    # from topic-config / jms-config extract + propagate rules.
                    try:
                        # 1. Look for auto-injected correlation ID stored in context
                        auto_corr_id = context.get(f"inject.{corr.message_id}._correlation_id")
                        inj_dest = ""

                        if auto_corr_id is None:
                            # 2. Try to extract from the injected message's payload/headers
                            inj_data = injections_dict.get(corr.message_id)
                            if inj_data:
                                inj_dest = inj_data.get("topic") or inj_data.get("destination", "")
                                inj_msg_type = "kafka"  # default; JMS injections still valid
                                inj_cfg = self._get_corr_config(inj_dest, inj_msg_type) or \
                                           self._get_corr_config(inj_dest, "jms")
                                if inj_cfg and inj_cfg.extract:
                                    from ..messaging.correlation import extract_correlation_id as _extract_corr
                                    auto_corr_id = _extract_corr(
                                        inj_data.get("payload"),
                                        inj_data.get("headers"),
                                        inj_cfg,
                                    )

                        if auto_corr_id:
                            correlation_value = auto_corr_id
                            # Derive target from expectation destination's extract/propagate rules
                            derived_target = None
                            exp_cfg = self._get_corr_config(expectation.topic, expectation.msg_type)
                            if exp_cfg:
                                # Use extract rules FIRST: these define how to read the
                                # correlation ID FROM a received message on this topic.
                                if exp_cfg.extract:
                                    first_rule = exp_cfg.extract[0]
                                    if first_rule.from_type == "header" and first_rule.name:
                                        derived_target = {"header": first_rule.name}
                                    elif first_rule.from_type == "jsonpath" and first_rule.expression:
                                        derived_target = {"jsonpath": first_rule.expression}
                                # Fallback: propagate.to_headers (where producer puts correlation ID)
                                if derived_target is None and exp_cfg.propagate and exp_cfg.propagate.to_headers:
                                    header_name = next(iter(exp_cfg.propagate.to_headers.keys()), None)
                                    if header_name:
                                        derived_target = {"header": header_name}

                            if derived_target:
                                # Patch the correlate object with derived target for
                                # the message-scanning loop below.
                                from .loader import TestCorrelation as _TC
                                from dataclasses import replace as _dc_replace_exp
                                expectation = _dc_replace_exp(
                                    expectation,
                                    correlate=_TC(
                                        message_id=corr.message_id,
                                        source=None,
                                        target=derived_target,
                                    ),
                                )
                                logger.info(
                                    f"Auto-derived correlation: value={auto_corr_id!r} "
                                    f"target={derived_target!r} "
                                    f"for expectation topic={expectation.topic!r}"
                                )
                            else:
                                # Have a correlation value but no target field — hard fail
                                _err = (
                                    f"Correlation auto-derive failed for message_id='{corr.message_id}': "
                                    f"extracted value={auto_corr_id!r} from '{inj_dest}' "
                                    f"but could not determine target field in topic '{expectation.topic}'. "
                                    f"Check topic-config for '{expectation.topic}' has "
                                    f"'correlation.propagate.to_headers' or 'correlation.extract' rules."
                                )
                                logger.error(f"test expectation #{exp_idx}: {_err}")
                                exp_result.error = _err
                                exp_result.status = "NO_MATCH"
                                exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                                return exp_result
                        else:
                            # Could not extract correlation ID from injected message — hard fail
                            _err = (
                                f"Correlation auto-derive failed for message_id='{corr.message_id}': "
                                f"could not extract correlation ID from injected message "
                                f"(topic '{inj_dest}'). "
                                f"Check topic-config for '{inj_dest}' has valid "
                                f"'correlation.extract' rules, or use explicit correlate.source/target."
                            )
                            logger.error(f"test expectation #{exp_idx}: {_err}")
                            exp_result.error = _err
                            exp_result.status = "NO_MATCH"
                            exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                            return exp_result
                    except Exception as _auto_exp_err:
                        _err = (
                            f"Correlation auto-derive error for message_id='{corr.message_id}': "
                            f"{_auto_exp_err}"
                        )
                        logger.error(f"test expectation #{exp_idx}: {_err}")
                        exp_result.error = _err
                        exp_result.status = "NO_MATCH"
                        exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                        return exp_result

            # Note: We don't check if listener is subscribed to this topic
            # because the listener only listens to INPUT topics (from rules),
            # not OUTPUT topics. The test will consume directly from Kafka via consume_latest()
            # which works regardless of listener subscription.

            # --- HTTP stub expectation ---
            # For type=http-stub, wait for the stub to have received its expected calls.
            if expectation.msg_type == "http-stub":
                stub_id = getattr(expectation, '_stub_id', None)
                if not stub_id or not self.stub_cache:
                    exp_result.status = "NO_MATCH"
                    exp_result.error = "HTTP stub not registered (stub_cache unavailable or stub_id missing)"
                    exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                    return exp_result

                # Block until expected_times calls arrive or timeout
                fulfilled = self.stub_cache.wait_for_stub(
                    stub_id=stub_id,
                    timeout_ms=expectation.wait_ms,
                )
                stub = self.stub_cache.get_stub(stub_id)
                actual_count = len(stub.calls) if stub else 0
                exp_result.received = actual_count
                exp_result.expected = expectation.times
                elapsed = int((time.time() - start_time) * 1000)
                exp_result.elapsed_ms = elapsed

                if not fulfilled or actual_count < expectation.times:
                    exp_result.status = "NO_MATCH"
                    exp_result.error = (
                        f"HTTP stub '{expectation.path}' expected {expectation.times} call(s), "
                        f"got {actual_count} within {expectation.wait_ms}ms"
                    )
                    return exp_result

                # Optionally evaluate match conditions against the recorded calls
                if expectation.match and stub:
                    for call in stub.calls:
                        call_body_json = call.body_json
                        for condition in expectation.match:
                            try:
                                matcher = self.matcher_factory.create(condition.type)
                                if condition.type == 'jsonpath':
                                    mc = {'path': condition.expression, 'value': condition.value, 'regex': condition.regex}
                                    result_m = matcher.match(call_body_json or {}, mc)
                                elif condition.type == 'header':
                                    result_m = matcher.match(call.headers, condition)
                                elif condition.type == 'path_param':
                                    result_m = matcher.match(call.path_params, condition)
                                elif condition.type == 'query_param':
                                    result_m = matcher.match(call.query_params, condition)
                                else:
                                    result_m = matcher.match(call.body, condition.value or condition.regex)
                                if not result_m.matched:
                                    exp_result.status = "NO_MATCH"
                                    exp_result.error = (
                                        f"HTTP stub condition {condition.type} not satisfied "
                                        f"in call to '{call.path}'"
                                    )
                                    return exp_result
                            except Exception as e:
                                logger.warning(f"Stub condition eval error: {e}")

                exp_result.status = "MATCHED"
                return exp_result

            # --- HTTP expectation ---
            # For type=http, validate the response from a previous HTTP injection (source_id).
            if expectation.msg_type == "http":
                http_result = when_result.http_results.get(expectation.source_id) if expectation.source_id else None
                if http_result is None:
                    exp_result.status = "NO_MATCH"
                    exp_result.error = f"No HTTP result found for source_id={expectation.source_id!r}"
                    exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                    return exp_result

                # Build a message-like dict from the HTTP response for condition matching
                http_msg = {
                    "value": http_result.body_json if http_result.body_json is not None else http_result.body,
                    "status_code": http_result.status_code,
                    "headers": http_result.response_headers,
                }
                matched = True
                for condition in expectation.match:
                    if condition.type == "status_code":
                        expected_code = int(condition.value) if condition.value is not None else None
                        if expected_code is not None and http_result.status_code != expected_code:
                            matched = False
                            break
                        if condition.regex:
                            import re
                            if not re.match(condition.regex, str(http_result.status_code)):
                                matched = False
                                break
                    elif condition.type == "response_header":
                        # condition.expression = header name
                        header_val = http_result.response_headers.get(condition.expression, "")
                        if condition.value is not None and str(header_val) != str(condition.value):
                            matched = False
                            break
                        if condition.regex:
                            import re
                            if not re.search(condition.regex, str(header_val)):
                                matched = False
                                break
                    else:
                        # Use standard matcher for jsonpath/exact/partial/regex on response body
                        matcher = self.matcher_factory.create(condition.type)
                        body = http_msg["value"]
                        if condition.type == 'jsonpath':
                            matcher_condition = {
                                'path': condition.expression,
                                'value': condition.value,
                                'regex': condition.regex,
                            }
                        else:
                            matcher_condition = condition
                        if not matcher.match(body, matcher_condition).matched:
                            matched = False
                            break

                if matched:
                    exp_result.status = "MATCHED"
                    exp_result.received = 1
                    exp_result.received_messages = [http_msg]
                else:
                    exp_result.status = "NO_MATCH"
                    exp_result.error = "HTTP response did not match conditions"
                exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                return exp_result

            # --- JMS expectation ---
            # Prefer reading from message_cache (populated by JMSListenerEngine) to
            # avoid concurrent MQGET calls on the shared IBM MQ hConn that trigger
            # MQRC_HCONN_ERROR (2018).  Fall back to jms_client.consume() only when
            # no cache is available (e.g. standalone/unit-test mode).
            if expectation.msg_type == "jms":
                if self.message_cache:
                    # Re-use the same cache-polling loop as the Kafka path below — the
                    # listener already wrote the produced messages into the cache, so we
                    # can read them without touching the IBM MQ hConn at all.
                    pass  # fall through to the shared Kafka/cache polling loop
                else:
                    # No cache available: consume directly from IBM MQ.
                    if not self.jms_registry or self.jms_registry.is_empty():
                        exp_result.status = "NO_MATCH"
                        exp_result.error = "JMS client not initialized"
                        exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                        return exp_result

                    jms_client = self.jms_registry.get_client(expectation.connection_ref)
                    jms_messages = jms_client.consume(
                        destination=expectation.destination,
                        limit=100,
                        timeout_ms=expectation.wait_ms
                    )

                    received_messages = []
                    all_received_messages = []

                    for msg in jms_messages:
                        if "error" in msg:
                            continue

                        msg_value = msg.get("value")
                        if isinstance(msg_value, str):
                            try:
                                msg_value = json.loads(msg_value)
                            except json.JSONDecodeError:
                                pass

                        msg_for_logging = ReceivedMessage(
                            value=msg_value,
                            timestamp=msg.get("timestamp", 0),
                            partition=msg.get("partition", 0),
                            offset=msg.get("offset", 0),
                            headers=msg.get("headers"),
                            key=msg.get("key")
                        )

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
                                    all_received_messages.append(msg_for_logging)
                                    continue
                            except Exception as e:
                                logger.warning(f"Failed to extract/match JMS target correlation: {e}")
                                all_received_messages.append(msg_for_logging)
                                continue

                        # Check match conditions
                        if expectation.match:
                            conditions_matched = 0
                            for condition in expectation.match:
                                try:
                                    matcher = self.matcher_factory.create(condition.type)
                                    if condition.type == 'jsonpath':
                                        matcher_condition = {'path': condition.expression, 'value': condition.value, 'regex': condition.regex}
                                        if matcher and matcher.match(msg_value, matcher_condition).matched:
                                            conditions_matched += 1
                                    elif condition.type == 'header':
                                        if matcher and matcher.match(msg.get('headers', {}), condition).matched:
                                            conditions_matched += 1
                                    else:
                                        if matcher and matcher.match(msg_value, condition).matched:
                                            conditions_matched += 1
                                except Exception as e:
                                    logger.debug(f"Error matching JMS condition: {e}")

                            if conditions_matched < len(expectation.match):
                                all_received_messages.append(msg_for_logging)
                                continue

                        received_messages.append(msg_for_logging)
                        all_received_messages.append(msg_for_logging)

                    exp_result.received = len(received_messages)
                    exp_result.received_messages = [asdict(m) for m in received_messages]
                    exp_result.status = "MATCHED" if received_messages else "TIMEOUT"
                    exp_result.elapsed_ms = int((time.time() - start_time) * 1000)
                    return exp_result

            # --- Kafka / cache polling loop ---
            # Used for:
            #   • Kafka expectations (always)
            #   • JMS expectations when message_cache is available (fall-through from above)
            #     The JMS listener engine writes every produced JMS message into the
            #     cache, so test expectations can read from it without touching the
            #     shared IBM MQ hConn (which would cause MQRC_HCONN_ERROR 2018).
            received_messages = []
            all_received_messages = []  # Track ALL messages for logging/closest match
            seen_message_keys = set()  # Track seen messages to avoid duplicates from cache
            end_time = time.time() + (expectation.wait_ms / 1000.0)
            last_cache_check_time = time.time()

            while time.time() < end_time:
                # Use cache if available, otherwise fall back to Kafka polling
                if self.message_cache:
                    # Get messages from cache received since the test started.
                    # Subtract 1 s safety margin so messages produced by the listener
                    # just before the expectation phase are never missed.
                    cache_since = (test_start_time - 1.0) if test_start_time is not None else start_time
                    cached_msgs = self.message_cache.get_messages(expectation.topic, since=cache_since)
                    messages = [
                        {
                            "value": m.value,
                            "timestamp": m.timestamp,
                            "partition": m.partition,
                            "offset": m.offset,
                            "headers": m.headers,
                            "key": m.key
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

                    # Verbose: log every new (non-duplicate) candidate message
                    _vtest(verbose, (
                        f"topic={expectation.topic!r} "
                        f"[expectation #{exp_idx}] evaluating message "
                        f"partition={msg.get('partition', 0)} offset={msg.get('offset', 0)} "
                        f"key={msg.get('key')!r} headers={msg.get('headers')} "
                        f"payload={json.dumps(msg.get('value'), default=str)[:500]}"
                    ))

                    # Filter messages to only those received after test start
                    # Apply a 1 s safety margin to handle slight timing differences.
                    # Use _to_seconds() to tolerate timestamps in either seconds or ms.
                    if test_start_time is not None:
                        msg_timestamp_seconds = _to_seconds(msg.get("timestamp", 0))
                        if msg_timestamp_seconds < test_start_time - 1.0:
                            logger.debug(f"Skipping message received before test start: {msg_timestamp_seconds} < {test_start_time - 1.0}")
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
                        headers=msg.get("headers"),
                        key=msg.get("key")
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
                                _vtest(verbose, (
                                    f"topic={expectation.topic!r} [expectation #{exp_idx}] "
                                    f"correlation MISMATCH: target={target!r} "
                                    f"expected={correlation_value!r} actual={target_value!r}"
                                ))
                                if test_logger:
                                    test_logger.log_received_message(
                                        topic=expectation.topic,
                                        payload=msg_value,
                                        correlation_matched=False,
                                        conditions_matched=0,
                                        total_conditions=len(expectation.match) if expectation.match else 0,
                                        headers=msg.get("headers"),
                                        key=msg.get("key"),
                                        correlation_mismatch={
                                            "target": target,
                                            "expected": str(correlation_value),
                                            "actual": str(target_value) if target_value is not None else None,
                                        },
                                    )
                                all_received_messages.append(msg_for_logging)
                                continue
                            correlation_matched = True
                            _vtest(verbose, (
                                f"topic={expectation.topic!r} [expectation #{exp_idx}] "
                                f"correlation MATCH: target={target!r} value={correlation_value!r}"
                            ))
                        except Exception as e:
                            logger.warning(f"Failed to extract/match target correlation: {e}")
                            if test_logger:
                                test_logger.log_received_message(
                                    topic=expectation.topic,
                                    payload=msg_value,
                                    correlation_matched=False,
                                    conditions_matched=0,
                                    total_conditions=len(expectation.match) if expectation.match else 0,
                                    headers=msg.get("headers"),
                                    key=msg.get("key"),
                                    correlation_mismatch={"target": target, "error": str(e)},
                                )
                            all_received_messages.append(msg_for_logging)
                            continue
                    elif not expectation.correlate or not expectation.correlate.target:
                        # No correlation matching needed
                        correlation_matched = True

                    # Check conditions
                    if expectation.match:
                        conditions_matched = 0
                        failed_conditions_details = []
                        condition_results = []  # Track all condition results for logging

                        for idx, condition in enumerate(expectation.match):
                            try:
                                matcher = self.matcher_factory.create(condition.type)
                                condition_matched = False
                                match_result = None

                                # ── Render condition value/regex with then-block template context ──
                                # This allows placeholders like {{testId}}, {{inject.order1.field}},
                                # {{myCustomPlaceholder}}, {{uuid}}, {{a | b | "default"}} in match values.
                                def _render_condition_val(raw_val):
                                    if raw_val is None:
                                        return None
                                    rendered_str = TemplateRenderer.render(str(raw_val), _template_ctx)
                                    # Try to recover natural type (float/int/bool) so numeric
                                    # comparisons still work after rendering.
                                    try:
                                        import json as _json
                                        return _json.loads(rendered_str)
                                    except (ValueError, TypeError):
                                        return rendered_str

                                rendered_val = _render_condition_val(condition.value)
                                rendered_regex = (
                                    TemplateRenderer.render(str(condition.regex), _template_ctx)
                                    if condition.regex is not None else None
                                )
                                # Create a rendered copy of the condition for matchers that
                                # accept the condition object directly (header, key, etc.)
                                from dataclasses import replace as _dc_replace
                                rendered_condition = _dc_replace(
                                    condition, value=rendered_val, regex=rendered_regex
                                )

                                # Build matcher-specific condition dict and run match
                                if condition.type == 'jsonpath':
                                    matcher_condition = {
                                        'path': condition.expression,
                                        'value': rendered_val,
                                        'regex': rendered_regex
                                    }
                                    match_result = matcher.match(msg_value, matcher_condition) if matcher else None
                                elif condition.type == 'header':
                                    headers_dict = msg.get('headers', {})
                                    match_result = matcher.match(headers_dict, rendered_condition) if matcher else None
                                elif condition.type == 'key':
                                    msg_key = msg.get('key')
                                    match_result = matcher.match(msg_key, rendered_condition) if matcher else None
                                else:
                                    match_result = matcher.match(msg_value, rendered_condition) if matcher else None

                                condition_matched = bool(match_result and match_result.matched)
                                if condition_matched:
                                    conditions_matched += 1

                                # Emit one verbose line per condition (mirrors VERBOSE-RULES format)
                                if verbose:
                                    _vtest(verbose, _format_condition_vtest(
                                        exp_idx=exp_idx,
                                        topic=expectation.topic,
                                        idx=idx,
                                        condition=condition,
                                        matched=condition_matched,
                                        msg_value=msg_value,
                                        msg=msg,
                                    ))

                                # Record condition result
                                condition_results.append({
                                    'index': idx,
                                    'type': condition.type,
                                    'matched': condition_matched,
                                    'expression': getattr(condition, 'expression', None),
                                    'value': getattr(condition, 'value', None),
                                    'regex': getattr(condition, 'regex', None)
                                })

                                # Track failed conditions
                                if not condition_matched:
                                    # Determine the actual received value for useful display
                                    def _actual_value(ctype, expression, mv, m):
                                        if ctype == 'jsonpath' and expression:
                                            try:
                                                from jsonpath_ng import parse as _jp_parse
                                                _matches = _jp_parse(expression).find(
                                                    json.loads(mv) if isinstance(mv, str) else mv
                                                )
                                                if _matches:
                                                    return _matches[0].value
                                                return "(field not found)"
                                            except Exception:
                                                return "(field not found)"
                                        elif ctype == 'header':
                                            return (m.get('headers') or {}).get(expression)
                                        elif ctype == 'key':
                                            return m.get('key')
                                        else:
                                            return mv

                                    failed_conditions_details.append({
                                        'position': idx,
                                        'type': condition.type,
                                        'expression': getattr(condition, 'expression', None),
                                        'expected': {
                                            'value': getattr(condition, 'value', None),
                                            'regex': getattr(condition, 'regex', None)
                                        },
                                        'actual': _actual_value(
                                            condition.type,
                                            getattr(condition, 'expression', None),
                                            msg_value,
                                            msg
                                        )
                                    })
                            except Exception as e:
                                logger.debug(f"Error matching condition: {e}")
                                failed_conditions_details.append({
                                    'position': idx,
                                    'type': getattr(condition, 'type', 'unknown'),
                                    'error': str(e)
                                })
                                if verbose:
                                    _vtest(verbose, (
                                        f"topic={expectation.topic!r} [expectation #{exp_idx}] "
                                        f"condition #{idx} ({getattr(condition, 'type', '?')}) ✗ ERROR: {e}"
                                    ))

                        if conditions_matched < len(expectation.match):
                            # Summary NO MATCH line after per-condition detail
                            _vtest(verbose, (
                                f"topic={expectation.topic!r} "
                                f"[expectation #{exp_idx}] ✗ NO MATCH "
                                f"conditions {conditions_matched}/{len(expectation.match)} passed "
                                f"payload={json.dumps(msg_value, default=str)[:500]}"
                            ))
                            if test_logger:
                                test_logger.log_received_message(
                                    topic=expectation.topic,
                                    payload=msg_value,
                                    correlation_matched=correlation_matched,
                                    conditions_matched=conditions_matched,
                                    total_conditions=len(expectation.match),
                                    headers=msg.get("headers"),
                                    key=msg.get("key"),
                                    failed_conditions=failed_conditions_details
                                )
                            all_received_messages.append(msg_for_logging)
                            continue

                    # Message matches all conditions!
                    received_messages.append(msg_for_logging)
                    all_received_messages.append(msg_for_logging)

                    _vtest(verbose, (
                        f"topic={expectation.topic!r} "
                        f"[expectation #{exp_idx}] ✓ MATCH "
                        f"partition={msg.get('partition', 0)} offset={msg.get('offset', 0)} "
                        f"payload={json.dumps(msg_value, default=str)[:500]}"
                    ))

                    # Always log matching message
                    if test_logger:
                        test_logger.log_received_message(
                            topic=expectation.topic,
                            payload=msg_value,
                            correlation_matched=correlation_matched,
                            conditions_matched=conditions_matched,
                            total_conditions=len(expectation.match) if expectation.match else 0,
                            headers=msg.get("headers"),
                            key=msg.get("key")
                        )

                if received_messages:
                    break

                # Wait for the cache to signal a new message (event-driven) rather
                # than sleeping a fixed 100 ms.  Cap individual waits at 50 ms so we
                # still re-check the deadline and handle the no-cache fallback path.
                remaining = end_time - time.time()
                if remaining <= 0:
                    break
                wait_s = min(0.05, remaining)
                if self.message_cache:
                    await asyncio.to_thread(self.message_cache.wait_for_new_message, wait_s)
                else:
                    await asyncio.sleep(wait_s)

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
        listener_engine = None,
        jms_registry = None,          # Optional JMS registry for JMS injection/expectation support
        http_executor = None,         # Optional HttpExecutor for HTTP injection/expectation support
        stub_cache: Optional["HttpStubCache"] = None,  # Optional HTTP stub cache
        db_executor = None,           # Optional DBExecutor for type=db actions
        topic_config_loader = None,   # Optional TopicConfigLoader for auto correlation
        jms_config_loader = None,     # Optional JMSConfigLoader for auto correlation
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
            listener_engine=listener_engine,
            jms_registry=jms_registry,
            http_executor=http_executor,
            stub_cache=stub_cache,
            db_executor=db_executor,
            topic_config_loader=topic_config_loader,
            jms_config_loader=jms_config_loader,
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

