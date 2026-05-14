"""
Mock HTTP Dispatch Handler.

Evaluates inbound requests from the mock servers against a priority-ordered
set of layers and returns a DispatchResult containing:
  - The HTTP response (status, body, headers)
  - A list of *pre-rendered* post-response coroutines that should be
    launched (via asyncio.create_task) just before the Response is returned.

Dispatch priority:
  1. HttpStubCache          — active test stubs (highest priority)
  2. ConfigLoader rules     — when.type=http rules (hot-reload free)
  3. Server endpoint defaults — from mock-server.yaml  endpoints section
  4. Server default response  — from mock-server.yaml  default_response
  5. Built-in 404           — if nothing matches

Sync / Async ordering in then-block:
  Items before the first ``type: http_response`` output → executed synchronously
  The ``type: http_response`` item → defines the HTTP reply
  Items after ``type: http_response`` → rendered NOW (context snapshot),
    returned as coroutines to be launched just before the Reply is sent.
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Coroutine, Dict, List, Optional, Tuple

from ..config.loader import ConfigLoader
from ..config.models import Output, Rule
from ..config.mock_server_config import EndpointDefault, MockServerConfig
from ..http.stub_cache import HttpStub, HttpStubCache
from ..rules.matcher import MatcherFactory
from ..rules.templater import TemplateRenderer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


def _compile_path_pattern(pattern: str) -> re.Pattern:
    """Convert ``/orders/{orderId}`` → named-group regex."""
    escaped = re.escape(pattern)
    named = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", escaped)
    return re.compile(f"^{named}$")


# Simple LRU-ish regex cache (unbounded for now, patterns are finite)
_PATTERN_CACHE: Dict[str, re.Pattern] = {}


def _get_pattern(path_pattern: str) -> re.Pattern:
    if path_pattern not in _PATTERN_CACHE:
        _PATTERN_CACHE[path_pattern] = _compile_path_pattern(path_pattern)
    return _PATTERN_CACHE[path_pattern]


def _try_json(body: str) -> Optional[Any]:
    try:
        return json.loads(body) if body else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DispatchResult:
    status_code: int
    body: str
    response_headers: Dict[str, str]
    content_type: str
    matched_by: str                              # "stub" | "rule" | "endpoint_default" | "server_default" | "no_match"
    post_response_coros: List[Coroutine] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class MockDispatchHandler:
    """
    Shared dispatcher wired to all mock servers.  Each HttpMockServer calls
    ``await dispatch(server_name, method, path, headers, body_bytes, query_params)``.
    """

    def __init__(
        self,
        config_loader: ConfigLoader,
        server_configs: Dict[str, MockServerConfig],
        stub_cache: HttpStubCache,
        kafka_client=None,
        jms_registry=None,
        http_executor=None,
    ):
        self.config_loader = config_loader
        self.server_configs = server_configs
        self.stub_cache = stub_cache
        self.kafka_client = kafka_client
        self.jms_registry = jms_registry
        self.http_executor = http_executor

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        server_name: str,
        method: str,
        path: str,
        headers: Dict[str, str],
        body_bytes: bytes,
        query_params: Dict[str, str],
    ) -> DispatchResult:
        """Evaluate the request against all priority layers and return a result."""

        body = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""
        body_json = _try_json(body)

        # --- Layer 1: stub cache ---
        stub = self.stub_cache.match(
            server_name=server_name,
            method=method,
            path=path,
            headers=headers,
            body=body,
            body_json=body_json,
            query_params=query_params,
        )
        if stub is not None:
            return await self._result_from_stub(stub, path, query_params, headers, body, body_json)

        # --- Layer 2: config rules ---
        rule_result = await self._try_rule_match(
            server_name=server_name,
            method=method,
            path=path,
            headers=headers,
            body=body,
            body_json=body_json,
            query_params=query_params,
        )
        if rule_result is not None:
            return rule_result

        # --- Layer 3 & 4: server config defaults ---
        server_cfg = self.server_configs.get(server_name)
        if server_cfg:
            endpoint_result = self._try_endpoint_default(
                server_cfg, method, path, headers, body, body_json, query_params
            )
            if endpoint_result is not None:
                return endpoint_result

            return DispatchResult(
                status_code=server_cfg.default_status_code,
                body=server_cfg.default_payload or "",
                response_headers=dict(server_cfg.default_headers or {}),
                content_type=server_cfg.default_content_type,
                matched_by="server_default",
            )

        # --- Layer 5: built-in no-match ---
        logger.debug(f"No match for {method} {path} on server '{server_name}'")
        return DispatchResult(
            status_code=404,
            body=json.dumps({"error": "no matching rule or stub", "path": path, "method": method}),
            response_headers={"Content-Type": "application/json"},
            content_type="application/json",
            matched_by="no_match",
        )

    # ------------------------------------------------------------------
    # Stub response
    # ------------------------------------------------------------------

    async def _result_from_stub(
        self,
        stub: HttpStub,
        path: str,
        query_params: Dict[str, str],
        headers: Dict[str, str],
        body: str,
        body_json: Any,
    ) -> DispatchResult:
        """Build a DispatchResult from a matched stub."""
        # Build context for template rendering in the stub response payload
        path_params = stub.match_path(path) or {}
        context = self._build_context(path_params, query_params, headers, body, body_json)
        rendered_payload = TemplateRenderer.render(stub.response_payload or "", context)
        rendered_headers = {
            k: TemplateRenderer.render(v, context)
            for k, v in (stub.response_headers or {}).items()
        }
        rendered_headers.setdefault("Content-Type", stub.response_content_type)

        logger.info(
            f"[HTTP-MOCK] stub match: '{stub.stub_id}' → "
            f"{stub.response_status} (test: {stub.test_id})"
        )
        return DispatchResult(
            status_code=stub.response_status,
            body=rendered_payload,
            response_headers=rendered_headers,
            content_type=stub.response_content_type,
            matched_by="stub",
        )

    # ------------------------------------------------------------------
    # Rule matching
    # ------------------------------------------------------------------

    async def _try_rule_match(
        self,
        server_name: str,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: str,
        body_json: Any,
        query_params: Dict[str, str],
    ) -> Optional[DispatchResult]:
        """Attempt to find a matching http-type rule and execute it."""

        all_rules = self.config_loader.get_all_rules()
        http_rules = [
            r for r in all_rules
            if r.input_type == "http"
            and not r.skip
            and (
                r.connection_ref == server_name
                or (r.connection_ref is None and self._is_default_server(server_name))
            )
        ]

        for rule in http_rules:
            # Method filter
            if rule.input_method != "*" and rule.input_method != method.upper():
                continue

            # Path match
            path_params = self._extract_path_params(rule.input_destination, path)
            if path_params is None:
                continue

            # Build context for condition evaluation
            context = self._build_context(path_params, query_params, headers, body, body_json)

            # Evaluate match conditions
            if not self._evaluate_conditions(rule, body, body_json, headers, path_params, query_params):
                continue

            # Found a matching rule — execute it
            logger.info(f"[HTTP-MOCK] rule match: '{rule.rule_name}' → {method} {path}")
            return await self._execute_rule(rule, context)

        return None

    def _is_default_server(self, server_name: str) -> bool:
        """True when there is exactly one server and connection_ref was omitted."""
        return len(self.server_configs) == 1

    def _evaluate_conditions(
        self,
        rule: Rule,
        body: str,
        body_json: Any,
        headers: Dict[str, str],
        path_params: Dict[str, str],
        query_params: Dict[str, str],
    ) -> bool:
        if not rule.conditions:
            return True  # wildcard
        for condition in rule.conditions:
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
                    mc = condition.regex if condition.regex else condition.value
                    result = matcher.match(body, mc)
                if not result.matched:
                    return False
            except Exception as e:
                logger.warning(f"Condition eval error in rule '{rule.rule_name}': {e}")
                return False
        return True

    # ------------------------------------------------------------------
    # Rule execution with sync/async split
    # ------------------------------------------------------------------

    async def _execute_rule(self, rule: Rule, context: Dict[str, Any]) -> DispatchResult:
        """
        Split rule outputs into pre-response (sync) / http_response / post-response (async).
        Pre-response outputs are awaited immediately.
        Post-response coroutines are built (context snapshot baked in) and returned for
        the caller to launch just before sending the HTTP response.
        """
        pre_outputs: List[Output] = []
        http_response_output: Optional[Output] = None
        post_outputs: List[Output] = []

        for out in rule.outputs:
            if http_response_output is None:
                if out.msg_type == "http_response":
                    http_response_output = out
                else:
                    pre_outputs.append(out)
            else:
                post_outputs.append(out)

        # Execute pre-response outputs synchronously
        for out in pre_outputs:
            try:
                if out.delay_ms and out.delay_ms > 0:
                    await asyncio.sleep(out.delay_ms / 1000.0)
                await self._execute_output(out, context)
            except Exception as e:
                logger.error(f"Pre-response output execution error (rule '{rule.rule_name}'): {e}")

        # Build the HTTP response
        if http_response_output is None:
            # Rule has no http_response output → 200 + empty body (unusual but allowed)
            status, body, resp_headers, ct = 200, "", {}, "application/json"
        else:
            out = http_response_output
            rendered_body = TemplateRenderer.render(out.payload or "", context)
            rendered_headers = {
                k: TemplateRenderer.render(v, context)
                for k, v in (out.headers or {}).items()
            }
            ct = out.response_content_type or "application/json"
            rendered_headers.setdefault("Content-Type", ct)
            status, body, resp_headers = out.status_code, rendered_body, rendered_headers

        # Prepare post-response coroutines (render NOW with live context snapshot)
        post_coros: List[Coroutine] = []
        for out in post_outputs:
            try:
                coro = self._prepare_post_response_coro(out, dict(context))
                post_coros.append(coro)
            except Exception as e:
                logger.error(f"Post-response coro preparation error (rule '{rule.rule_name}'): {e}")

        return DispatchResult(
            status_code=status,
            body=body,
            response_headers=resp_headers,
            content_type=ct,
            matched_by="rule",
            post_response_coros=post_coros,
        )

    # ------------------------------------------------------------------
    # Output execution
    # ------------------------------------------------------------------

    async def _execute_output(self, output: Output, context: Dict[str, Any]) -> None:
        """Execute a single non-http_response output (Kafka / JMS / HTTP call)."""
        try:
            rendered_payload = TemplateRenderer.render(output.payload or "", context)
            rendered_headers = {
                k: TemplateRenderer.render(v, context)
                for k, v in (output.headers or {}).items()
            } if output.headers else None

            output_type = output.msg_type.lower()

            if output_type == "kafka":
                if not self.kafka_client:
                    logger.error("Kafka client not available; skipping Kafka output")
                    return
                try:
                    message = json.loads(rendered_payload)
                except Exception:
                    message = rendered_payload

                rendered_key = None
                if output.key:
                    rendered_key = TemplateRenderer.render(output.key, context)

                self.kafka_client.produce(
                    output.destination,
                    message,
                    headers=rendered_headers,
                    key=rendered_key,
                    schema_id=output.schema_id,
                )
                logger.info(f"[HTTP-MOCK] Kafka → {output.destination}")

            elif output_type == "jms":
                if not self.jms_registry or self.jms_registry.is_empty():
                    logger.error("JMS registry not available; skipping JMS output")
                    return
                jms_client = self.jms_registry.get_client(output.connection_ref)
                jms_client.put_message(
                    destination=output.destination,
                    payload=rendered_payload,
                    headers=rendered_headers,
                )
                logger.info(f"[HTTP-MOCK] JMS → {output.destination}")

            elif output_type == "http":
                if not self.http_executor:
                    logger.error("HTTP executor not available; skipping HTTP output")
                    return
                rendered_url = TemplateRenderer.render(output.destination, context)
                rendered_query = None
                if output.query_params:
                    rendered_query = {k: TemplateRenderer.render(v, context) for k, v in output.query_params.items()}
                http_result = await self.http_executor.execute(
                    url=rendered_url,
                    method=output.method,
                    payload=rendered_payload if output.payload else None,
                    headers=rendered_headers,
                    query_params=rendered_query,
                    auth_ref=output.auth_ref,
                    tls_ref=output.tls_ref,
                    timeout_ms=output.http_timeout_ms,
                )
                logger.info(f"[HTTP-MOCK] HTTP {output.method} {rendered_url} → {http_result.status_code}")

        except Exception as e:
            logger.error(f"Output execution error ({output.msg_type} → {output.destination}): {e}")

    async def _prepare_post_response_coro(
        self, output: Output, context_snapshot: Dict[str, Any]
    ) -> None:
        """
        Render all templates NOW (context snapshot) and return a coroutine
        that only performs the I/O part.  The coroutine is self-contained
        and does not reference live context objects.
        """
        # Apply delay if configured
        if output.delay_ms and output.delay_ms > 0:
            await asyncio.sleep(output.delay_ms / 1000.0)
        await self._execute_output(output, context_snapshot)

    # ------------------------------------------------------------------
    # Endpoint-default matching
    # ------------------------------------------------------------------

    def _try_endpoint_default(
        self,
        server_cfg: MockServerConfig,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: str,
        body_json: Any,
        query_params: Dict[str, str],
    ) -> Optional[DispatchResult]:
        for ep in server_cfg.endpoints:
            if ep.method != "*" and ep.method.upper() != method.upper():
                continue
            params = self._extract_path_params(ep.path_pattern, path)
            if params is None:
                continue
            context = self._build_context(params, query_params, headers, body, body_json)
            rendered_payload = TemplateRenderer.render(ep.payload or "", context)
            rendered_headers = {
                k: TemplateRenderer.render(v, context)
                for k, v in (ep.headers or {}).items()
            }
            rendered_headers.setdefault("Content-Type", ep.content_type)
            logger.debug(f"[HTTP-MOCK] endpoint default match: {ep.path_pattern}")
            return DispatchResult(
                status_code=ep.status_code,
                body=rendered_payload,
                response_headers=rendered_headers,
                content_type=ep.content_type,
                matched_by="endpoint_default",
            )
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_path_params(self, pattern: str, path: str) -> Optional[Dict[str, str]]:
        """Return named path params if *path* matches *pattern*, else None."""
        try:
            regex = _get_pattern(pattern)
            m = regex.match(path)
            if m is None:
                return None
            return m.groupdict()
        except Exception as e:
            logger.warning(f"Path pattern compile/match error ('{pattern}'): {e}")
            return None

    def _build_context(
        self,
        path_params: Dict[str, str],
        query_params: Dict[str, str],
        headers: Dict[str, str],
        body: str,
        body_json: Any,
    ) -> Dict[str, Any]:
        """Build the template + condition evaluation context."""
        ctx: Dict[str, Any] = {}

        # Path parameters — accessible as {{path.orderId}}
        for k, v in path_params.items():
            ctx[f"path.{k}"] = v

        # Query parameters — accessible as {{query.page}}
        for k, v in query_params.items():
            ctx[f"query.{k}"] = v

        # Request headers — accessible as {{header.Content-Type}}
        for k, v in headers.items():
            ctx[f"header.{k}"] = v

        # Body fields (JSONPath-style) — accessible as {{$.fieldName}} or {{fieldName}}
        if isinstance(body_json, dict):
            ctx["message"] = body_json
            ctx["$"] = body_json
            for k, v in body_json.items():
                ctx[k] = v
                ctx[f"$.{k}"] = v
                if isinstance(v, dict):
                    for nk, nv in v.items():
                        ctx[f"{k}.{nk}"] = nv
                        ctx[f"$.{k}.{nk}"] = nv

        ctx["full_message"] = body

        # Standard placeholders
        import uuid as _uuid
        from datetime import datetime, timezone
        ctx["uuid"] = str(_uuid.uuid4())
        ctx["now"] = datetime.now(timezone.utc).isoformat() + "Z"

        return ctx


