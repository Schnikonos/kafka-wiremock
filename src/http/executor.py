"""
HTTP executor for kafka-wiremock.

Executes HTTP(S) requests with TLS and auth profile resolution.
Used by the test suite (type=http injections) and rule outputs (type=http then-items).
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union
from urllib.parse import urlparse

import httpx

from ..test.loader import HttpInjectionResult
from .tls_config import TlsConfigLoader, TlsProfile
from .auth_config import AuthConfigLoader, AuthProfile

logger = logging.getLogger(__name__)


class HttpExecutor:
    """
    Executes HTTP(S) requests applying TLS and auth configuration.

    Priority for TLS profile resolution:
      1. Explicit tls_ref on the injection/output (matches a named profile)
      2. Host-based match in tls.yaml host_overrides (first match)
      3. Default profile from tls.yaml
      4. Built-in default (verify=True, no client cert)

    Priority for auth profile resolution:
      1. Explicit auth_ref on the injection/output (matches a named profile)
      2. Host-based match in auth.yaml host_overrides (first match)
      3. No auth
    """

    def __init__(
        self,
        config_dir: Optional[Union[str, Path]] = None,
    ):
        config_dir = Path(config_dir) if config_dir else None
        tls_path = config_dir / "http-config" / "tls.yaml" if config_dir else None
        auth_path = config_dir / "http-config" / "auth.yaml" if config_dir else None

        self.tls_loader = TlsConfigLoader(tls_path)
        self.auth_loader = AuthConfigLoader(auth_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        url: str,
        method: str = "POST",
        payload: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        query_params: Optional[Dict[str, str]] = None,
        auth_ref: Optional[str] = None,
        tls_ref: Optional[str] = None,
        timeout_ms: int = 10000,
        message_id: str = "",
    ) -> HttpInjectionResult:
        """
        Execute an HTTP request and return the captured result.

        Args:
            url:          Full URL to call.
            method:       HTTP method (GET, POST, PUT, DELETE, PATCH, …).
            payload:      Request body (string; sent as-is).
            headers:      Additional request headers.
            query_params: URL query parameters.
            auth_ref:     Explicit auth profile name (overrides host-match).
            tls_ref:      Explicit TLS profile name (overrides host-match).
            timeout_ms:   Request timeout in milliseconds.
            message_id:   Logical message ID (for logging / result key).

        Returns:
            HttpInjectionResult with status_code, response_headers, body, body_json.
        """
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port

        # Resolve TLS profile
        tls_profile = self._resolve_tls(host, port, tls_ref)
        tls_kwargs = tls_profile.httpx_ssl_kwargs()

        # Resolve auth profile
        auth_profile = self._resolve_auth(host, port, auth_ref)

        # Build request headers
        req_headers: Dict[str, str] = dict(headers or {})

        # Apply authentication
        if auth_profile:
            self._apply_auth(auth_profile, req_headers, tls_kwargs)

        # Detect Content-Type for payload
        if payload is not None and "content-type" not in {k.lower() for k in req_headers}:
            stripped = payload.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                req_headers["Content-Type"] = "application/json"
            else:
                req_headers["Content-Type"] = "text/plain; charset=utf-8"

        timeout = httpx.Timeout(timeout_ms / 1000.0)

        try:
            async with httpx.AsyncClient(timeout=timeout, **tls_kwargs) as client:
                response = await client.request(
                    method=method.upper(),
                    url=url,
                    content=payload.encode("utf-8") if payload else None,
                    headers=req_headers,
                    params=query_params,
                )

            resp_headers = dict(response.headers)
            body_text = response.text

            # Try to parse JSON body
            body_json = None
            ct = resp_headers.get("content-type", "")
            if "json" in ct or body_text.strip().startswith(("{", "[")):
                try:
                    body_json = response.json()
                except Exception:
                    body_json = None

            logger.debug(
                f"HTTP {method.upper()} {url} → {response.status_code} "
                f"(message_id={message_id!r}, body_len={len(body_text)})"
            )
            return HttpInjectionResult(
                message_id=message_id,
                status_code=response.status_code,
                response_headers=resp_headers,
                body=body_text,
                body_json=body_json,
            )

        except httpx.TimeoutException as e:
            msg = f"HTTP {method.upper()} {url} timed out after {timeout_ms}ms: {e}"
            logger.error(msg)
            return HttpInjectionResult(message_id=message_id, status_code=0, error=msg)
        except Exception as e:
            msg = f"HTTP {method.upper()} {url} failed: {e}"
            logger.error(msg)
            return HttpInjectionResult(message_id=message_id, status_code=0, error=msg)

    # ------------------------------------------------------------------
    # Profile resolution helpers
    # ------------------------------------------------------------------

    def _resolve_tls(self, host: str, port: Optional[int], tls_ref: Optional[str]) -> TlsProfile:
        if tls_ref:
            profile = self.tls_loader._config.profiles.get(tls_ref) if self.tls_loader._config else None
            if profile:
                return profile
            logger.warning(f"TLS profile '{tls_ref}' not found; falling back to host-match")
        return self.tls_loader.get_profile_for(host, port)

    def _resolve_auth(self, host: str, port: Optional[int], auth_ref: Optional[str]) -> Optional[AuthProfile]:
        if auth_ref:
            profile = self.auth_loader.get_profile_by_name(auth_ref)
            if profile:
                return profile
            logger.warning(f"Auth profile '{auth_ref}' not found; falling back to host-match")
        return self.auth_loader.get_profile_for(host, port)

    def _apply_auth(
        self,
        profile: AuthProfile,
        headers: Dict[str, str],
        tls_kwargs: Dict[str, Any],
    ) -> None:
        """Mutate *headers* to inject the appropriate auth."""
        if profile.auth_type == "basic":
            import base64
            user = profile.username or ""
            password = profile.get_password() or ""
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"

        elif profile.auth_type in ("bearer", "token_fetch"):
            token = profile.get_bearer_token(tls_kwargs)
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                logger.warning(f"Could not obtain bearer token for profile '{profile.name}'")

        elif profile.auth_type == "certificate":
            # mTLS authentication is handled entirely via TLS profile (cert/key in tls_kwargs).
            # Nothing to add to request headers.
            pass

        elif profile.auth_type != "none":
            logger.warning(f"Unknown auth type '{profile.auth_type}' for profile '{profile.name}'")

    def reload(self) -> None:
        """Reload TLS and auth configs from disk."""
        self.tls_loader.reload()
        self.auth_loader.reload()

