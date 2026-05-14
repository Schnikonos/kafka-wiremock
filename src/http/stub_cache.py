"""
HTTP Stub Cache — active test stubs registered by TestSuiteRunner.

When a test with ``type: http-stub`` expectations runs, it registers stubs
here *before* the ``when.inject`` phase fires.  When a mock server receives
a matching request, it records the call and signals any waiting test so the
expectation can be evaluated.

Thread-safety: all mutations are protected by ``_lock``.
"""
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from ..config.models import Condition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path-pattern compilation helper
# ---------------------------------------------------------------------------

_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def compile_path_pattern(pattern: str) -> re.Pattern:
    """
    Convert a ``/orders/{orderId}/items/{itemId}`` style pattern to a
    named-group regex: ``^/orders/(?P<orderId>[^/]+)/items/(?P<itemId>[^/]+)$``
    """
    escaped = re.escape(pattern)
    # re.escape turns { → \{, so we look for \\\{ and \\\}
    named_group = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", escaped)
    return re.compile(f"^{named_group}$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class HttpStubCall:
    """A single recorded inbound call that matched a stub."""
    timestamp: float
    method: str
    path: str
    headers: Dict[str, str]
    body: str
    body_json: Optional[Any]
    query_params: Dict[str, str]
    path_params: Dict[str, str]


@dataclass
class HttpStub:
    """
    An active stub: defines how the mock server should respond to a class of
    requests, and collects evidence that the calls actually happened.
    """
    stub_id: str
    test_id: str
    server_name: str
    path_pattern: str          # human-readable, e.g. "/orders/{orderId}"
    method: str                # HTTP method or "*"
    match_conditions: List[Condition]
    response_status: int = 200
    response_payload: Optional[str] = None
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_content_type: str = "application/json"
    expected_times: int = 1

    # Runtime state (not set by caller)
    calls: List[HttpStubCall] = field(default_factory=list)
    _path_regex: Optional[re.Pattern] = field(default=None, init=False, repr=False)
    _event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self):
        self._path_regex = compile_path_pattern(self.path_pattern)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match_path(self, path: str) -> Optional[Dict[str, str]]:
        """
        Return extracted path params if *path* matches this stub's pattern,
        else ``None``.
        """
        m = self._path_regex.match(path)
        if m is None:
            return None
        return m.groupdict()

    def match_method(self, method: str) -> bool:
        return self.method == "*" or self.method.upper() == method.upper()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_call(self, call: HttpStubCall) -> None:
        with self._lock:
            self.calls.append(call)
            call_count = len(self.calls)
        logger.debug(
            f"Stub '{self.stub_id}' received call {call_count}/{self.expected_times} "
            f"({call.method} {call.path})"
        )
        if call_count >= self.expected_times:
            self._event.set()

    # ------------------------------------------------------------------
    # Waiting
    # ------------------------------------------------------------------

    def wait(self, timeout_ms: int = 5000) -> bool:
        """Block until ``expected_times`` calls have been recorded (or timeout)."""
        return self._event.wait(timeout=timeout_ms / 1000.0)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class HttpStubCache:
    """
    Thread-safe registry of active HTTP stubs.

    Lifecycle per test:
      1. ``register(test_id, stub)``   — called for each http-stub expectation
      2. ``match(...)``                — called by MockDispatchHandler per request
      3. ``wait_for_stub(stub_id, ...)`` — called by TestSuiteRunner in then-phase
      4. ``cleanup_test(test_id)``     — called after test completes
    """

    def __init__(self):
        self._stubs: Dict[str, HttpStub] = {}   # stub_id → HttpStub
        self._by_test: Dict[str, List[str]] = {}  # test_id → [stub_id, ...]
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, test_id: str, stub: HttpStub) -> None:
        """Register a stub for a test run."""
        with self._lock:
            self._stubs[stub.stub_id] = stub
            self._by_test.setdefault(test_id, []).append(stub.stub_id)
        logger.debug(
            f"Registered HTTP stub '{stub.stub_id}' for test '{test_id}': "
            f"{stub.method} {stub.path_pattern} on server '{stub.server_name}'"
        )

    # ------------------------------------------------------------------
    # Matching (called per inbound request from MockDispatchHandler)
    # ------------------------------------------------------------------

    def match(
        self,
        server_name: str,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: str,
        body_json: Any,
        query_params: Dict[str, str],
    ) -> Optional[HttpStub]:
        """
        Find the first stub that matches the inbound request.

        Matching order: stubs registered earlier take priority.
        Returns the stub (with path_params already recorded on the call
        object) or ``None``.
        """
        from ..rules.matcher import MatcherFactory

        with self._lock:
            candidates = list(self._stubs.values())

        for stub in candidates:
            if stub.server_name != server_name:
                continue
            if not stub.match_method(method):
                continue

            path_params = stub.match_path(path)
            if path_params is None:
                continue

            # Evaluate additional match conditions
            if stub.match_conditions:
                all_matched = True
                for condition in stub.match_conditions:
                    try:
                        matcher = MatcherFactory.create(condition.type)
                        if condition.type == 'jsonpath':
                            mc = {'path': condition.expression, 'value': condition.value, 'regex': condition.regex}
                            result = matcher.match(body_json or {}, mc)
                        elif condition.type == 'header':
                            result = matcher.match(headers, condition)
                        elif condition.type == 'path_param':
                            result = matcher.match(path_params, condition)
                        elif condition.type == 'query_param':
                            result = matcher.match(query_params, condition)
                        else:
                            result = matcher.match(body, condition.value or condition.regex)
                        if not result.matched:
                            all_matched = False
                            break
                    except Exception as e:
                        logger.warning(f"HttpStubCache condition eval error: {e}")
                        all_matched = False
                        break
                if not all_matched:
                    continue

            # Record the call
            try:
                import json as _json
                body_json_parsed = _json.loads(body) if body else None
            except Exception:
                body_json_parsed = body_json

            call = HttpStubCall(
                timestamp=time.time(),
                method=method,
                path=path,
                headers=dict(headers),
                body=body,
                body_json=body_json_parsed,
                query_params=dict(query_params),
                path_params=path_params,
            )
            stub.record_call(call)
            return stub

        return None

    # ------------------------------------------------------------------
    # Waiting (called by TestSuiteRunner)
    # ------------------------------------------------------------------

    def wait_for_stub(self, stub_id: str, timeout_ms: int = 5000) -> bool:
        """Block until the stub has received its expected_times calls."""
        stub = self._stubs.get(stub_id)
        if stub is None:
            logger.warning(f"wait_for_stub: stub '{stub_id}' not found")
            return False
        return stub.wait(timeout_ms=timeout_ms)

    def get_stub(self, stub_id: str) -> Optional[HttpStub]:
        return self._stubs.get(stub_id)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_test(self, test_id: str) -> None:
        """Remove all stubs registered for a test."""
        with self._lock:
            stub_ids = self._by_test.pop(test_id, [])
            for sid in stub_ids:
                self._stubs.pop(sid, None)
        if stub_ids:
            logger.debug(f"Cleaned up {len(stub_ids)} HTTP stub(s) for test '{test_id}'")

    def get_stubs_for_test(self, test_id: str) -> List[HttpStub]:
        """Return all stubs registered for a test (snapshot)."""
        with self._lock:
            ids = list(self._by_test.get(test_id, []))
        return [s for sid in ids if (s := self._stubs.get(sid)) is not None]

