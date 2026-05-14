"""
Authentication configuration for HTTP requests.

Config file: config/http-config/auth.yaml

Structure:
  profiles:
    my_api:
      type: basic
      username: api_user
      # password: from env var  HTTP_AUTH_MY_API_PASSWORD  (profile name uppercased, dashes→underscores)

    bearer_static:
      type: bearer
      token: "my-static-token"         # inline static token
      # OR token_env: MY_API_TOKEN     # env var holding the token

    oauth_flow:
      type: token_fetch                # call an auth endpoint, extract token from response
      token_url: "https://auth.example.com/oauth/token"
      method: POST
      body: '{"grant_type":"client_credentials","client_id":"{{username}}","client_secret":"{{password}}"}'
      username: client_id_value
      # password: from env var  HTTP_AUTH_OAUTH_FLOW_PASSWORD
      token_response_path: "$.access_token"   # JSONPath
      token_cache_ttl_s: 3600         # 0 = no caching (default)

    cert_only:
      type: certificate               # authentication via mTLS client cert (configured in TLS profile)
      tls_profile: internal_certs     # must exist in tls.yaml profiles

  host_overrides:                     # Ordered; first match wins
    "api.example.com":
      profile: my_api
    "*.internal.corp.com":
      profile: cert_only
    "10.0.*":
      profile: bearer_static

Password env-var convention:
  For a profile named  "my_api"        → env var  HTTP_AUTH_MY_API_PASSWORD
  For a profile named  "oauth-flow"    → env var  HTTP_AUTH_OAUTH_FLOW_PASSWORD
  (profile name uppercased, non-alphanum chars replaced with _)
"""
import fnmatch
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


@dataclass
class AuthProfile:
    """Authentication settings for one logical endpoint group."""
    name: str
    auth_type: str = "none"           # none | basic | bearer | certificate | token_fetch

    # basic / token_fetch fields
    username: Optional[str] = None

    # bearer fields
    token: Optional[str] = None       # static inline token
    token_env: Optional[str] = None   # env var holding the token

    # token_fetch fields (auto-acquire bearer token by calling an auth API)
    token_url: Optional[str] = None
    token_method: str = "POST"
    token_body: Optional[str] = None  # template: may use {{username}} / {{password}}
    token_response_path: str = "$.access_token"
    token_cache_ttl_s: int = 0        # 0 = no caching

    # certificate auth
    tls_profile: Optional[str] = None  # name of TLS profile that carries the client cert

    # Internal cache
    _cached_token: Optional[str] = field(default=None, repr=False, compare=False)
    _token_cached_at: float = field(default=0.0, repr=False, compare=False)

    def _password_env_var(self) -> str:
        """Derive the env-var name for this profile's password."""
        safe = "".join(c if c.isalnum() else "_" for c in self.name.upper())
        return f"HTTP_AUTH_{safe}_PASSWORD"

    def get_password(self) -> Optional[str]:
        """Read password from environment variable."""
        return os.environ.get(self._password_env_var())

    def get_bearer_token(self, tls_kwargs: Dict[str, Any]) -> Optional[str]:
        """
        Return the bearer token for this profile.

        For type=bearer:    returns inline token or env-var token.
        For type=token_fetch: calls the token URL (with caching).
        """
        if self.auth_type == "bearer":
            if self.token:
                return self.token
            if self.token_env:
                return os.environ.get(self.token_env)
            return None

        if self.auth_type == "token_fetch":
            return self._fetch_token(tls_kwargs)

        return None

    def _fetch_token(self, tls_kwargs: Dict[str, Any]) -> Optional[str]:
        """Call the token_url and extract the bearer token (with TTL caching)."""
        now = time.time()
        if self.token_cache_ttl_s > 0 and self._cached_token is not None:
            if now - self._token_cached_at < self.token_cache_ttl_s:
                return self._cached_token

        try:
            import httpx
            from jsonpath_ng import parse as jp_parse

            password = self.get_password()
            body_str = self.token_body or ""
            body_str = body_str.replace("{{username}}", self.username or "")
            body_str = body_str.replace("{{password}}", password or "")

            headers: Dict[str, str] = {}
            body_data: Any = None
            if body_str.strip().startswith("{"):
                headers["Content-Type"] = "application/json"
                body_data = body_str
            else:
                # treat as form-encoded
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                body_data = body_str

            with httpx.Client(**tls_kwargs) as client:
                resp = client.request(
                    method=self.token_method.upper(),
                    url=self.token_url,
                    content=body_data.encode() if isinstance(body_data, str) else body_data,
                    headers=headers,
                    timeout=10.0,
                )
                resp.raise_for_status()
                resp_json = resp.json()

            expr = jp_parse(self.token_response_path)
            matches = expr.find(resp_json)
            token = str(matches[0].value) if matches else None

            if token:
                self._cached_token = token
                self._token_cached_at = now
                logger.debug(f"Fetched auth token for profile '{self.name}'")
            else:
                logger.warning(f"Auth token not found at '{self.token_response_path}' in response")
            return token

        except Exception as e:
            logger.error(f"Failed to fetch auth token for profile '{self.name}': {e}")
            return None

    def invalidate_token_cache(self) -> None:
        self._cached_token = None
        self._token_cached_at = 0.0


@dataclass
class AuthConfig:
    """Loaded auth configuration."""
    profiles: Dict[str, AuthProfile] = field(default_factory=dict)
    host_overrides: List[Tuple[str, AuthProfile]] = field(default_factory=list)


class AuthConfigLoader:
    """Loads and resolves auth configuration from YAML."""

    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        self._config: Optional[AuthConfig] = None
        self._config_path = Path(config_path) if config_path else None
        if self._config_path and self._config_path.exists():
            self._config = self._load(self._config_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_profile_by_name(self, name: str) -> Optional[AuthProfile]:
        if self._config is None:
            return None
        return self._config.profiles.get(name)

    def get_profile_for(self, host: str, port: Optional[int] = None) -> Optional[AuthProfile]:
        """Return the best-matching AuthProfile for a host[:port] (host-match only)."""
        if self._config is None:
            return None
        for pattern, profile in self._config.host_overrides:
            if _host_pattern_matches(pattern, host, port):
                return profile
        return None

    def get_all_profiles(self) -> Dict[str, AuthProfile]:
        if self._config is None:
            return {}
        return dict(self._config.profiles)

    def reload(self) -> None:
        if self._config_path and self._config_path.exists():
            self._config = self._load(self._config_path)

    # ------------------------------------------------------------------
    # Internal loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load(path: Path) -> AuthConfig:
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load auth config from {path}: {e}")
            return AuthConfig()

        profiles: Dict[str, AuthProfile] = {}
        for name, pdata in (data.get("profiles") or {}).items():
            profiles[name] = AuthConfigLoader._parse_profile(name, pdata)

        host_overrides: List[Tuple[str, AuthProfile]] = []
        raw_overrides = data.get("host_overrides") or {}
        if isinstance(raw_overrides, dict):
            items = list(raw_overrides.items())
        else:
            items = [(list(d.keys())[0], list(d.values())[0]) for d in raw_overrides]

        for pattern, override_data in items:
            if isinstance(override_data, dict) and "profile" in override_data:
                pname = override_data["profile"]
                if pname not in profiles:
                    logger.warning(f"Auth host override references unknown profile '{pname}'")
                    continue
                host_overrides.append((str(pattern), profiles[pname]))
            else:
                # Inline override — give it a synthetic name
                synthetic_name = f"__inline_{pattern}"
                host_overrides.append((str(pattern), AuthConfigLoader._parse_profile(synthetic_name, override_data or {})))

        return AuthConfig(profiles=profiles, host_overrides=host_overrides)

    @staticmethod
    def _parse_profile(name: str, data: Dict[str, Any]) -> AuthProfile:
        return AuthProfile(
            name=name,
            auth_type=str(data.get("type", "none")).lower(),
            username=data.get("username"),
            token=data.get("token"),
            token_env=data.get("token_env"),
            token_url=data.get("token_url"),
            token_method=str(data.get("method", "POST")).upper(),
            token_body=data.get("body"),
            token_response_path=str(data.get("token_response_path", "$.access_token")),
            token_cache_ttl_s=int(data.get("token_cache_ttl_s", 0)),
            tls_profile=data.get("tls_profile"),
        )


# ---------------------------------------------------------------------------
# Shared host-matching helper (same logic as tls_config, kept in sync)
# ---------------------------------------------------------------------------

def _host_pattern_matches(pattern: str, host: str, port: Optional[int]) -> bool:
    """Return True if the host pattern matches host[:port]."""
    if ":" in pattern:
        last_colon = pattern.rfind(":")
        host_part = pattern[:last_colon]
        port_part = pattern[last_colon + 1:]
    else:
        host_part = pattern
        port_part = None

    if not fnmatch.fnmatch(host.lower(), host_part.lower()):
        return False

    if port_part is None:
        return True
    if port is None:
        return False
    if "-" in port_part:
        try:
            lo, hi = port_part.split("-", 1)
            return int(lo) <= port <= int(hi)
        except ValueError:
            return False
    try:
        return port == int(port_part)
    except ValueError:
        return False

