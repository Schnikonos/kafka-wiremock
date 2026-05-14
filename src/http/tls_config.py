"""
TLS/Certificate configuration for HTTP requests.

Config file: config/http-config/tls.yaml

Structure:
  default:
    verify: true          # true, false, or path to CA bundle PEM
    # client_cert: /certs/client.pem
    # client_key: /certs/client.key
    # client_key_password_env: MY_CERT_KEY_PASSWORD   # env var name

  profiles:
    internal:
      verify: false
    corp:
      verify: /certs/corp-ca.pem
      client_cert: /certs/client.pem
      client_key: /certs/client.key
      client_key_password_env: CORP_CERT_KEY_PASSWORD

  host_overrides:           # Evaluated top-to-bottom; first match wins.
    "*.internal.corp.com":
      profile: internal
    "api.corp.com:8443-8449":   # port range
      profile: corp
    "legacy.example.com":
      verify: false

Host matching order (highest to lowest priority):
  1. Exact "host:port"
  2. Exact "host" (no port)
  3. Port-range  "host:start-end"   (glob on host part + range on port)
  4. Glob "host_pattern:port"       (fnmatch on host + exact port)
  5. Glob "host_pattern"            (fnmatch on host, any port)
  6. Default profile
"""
import fnmatch
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


@dataclass
class TlsProfile:
    """TLS settings for a group of hosts."""
    verify: Union[bool, str] = True   # True, False, or CA-bundle path
    client_cert: Optional[str] = None
    client_key: Optional[str] = None
    client_key_password_env: Optional[str] = None  # env var that holds the key password

    def get_client_key_password(self) -> Optional[str]:
        if self.client_key_password_env:
            return os.environ.get(self.client_key_password_env)
        return None

    def httpx_ssl_kwargs(self) -> Dict[str, Any]:
        """Return kwargs suitable for httpx.Client / AsyncClient."""
        kwargs: Dict[str, Any] = {}
        # verify
        kwargs["verify"] = self.verify
        # mTLS
        if self.client_cert and self.client_key:
            password = self.get_client_key_password()
            if password:
                # httpx expects (cert_path, key_path, password) or (cert_path, key_path)
                kwargs["cert"] = (self.client_cert, self.client_key, password)
            else:
                kwargs["cert"] = (self.client_cert, self.client_key)
        elif self.client_cert:
            kwargs["cert"] = self.client_cert
        return kwargs


@dataclass
class TlsConfig:
    """Loaded TLS configuration."""
    default: TlsProfile = field(default_factory=TlsProfile)
    profiles: Dict[str, TlsProfile] = field(default_factory=dict)
    # Ordered list of (pattern, profile) — evaluated top-to-bottom
    host_overrides: List[Tuple[str, TlsProfile]] = field(default_factory=list)


class TlsConfigLoader:
    """Loads and resolves TLS configuration from YAML."""

    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        self._config: Optional[TlsConfig] = None
        self._config_path = Path(config_path) if config_path else None
        if self._config_path and self._config_path.exists():
            self._config = self._load(self._config_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_profile_for(self, host: str, port: Optional[int] = None) -> TlsProfile:
        """Return the best-matching TlsProfile for a given host[:port]."""
        if self._config is None:
            return TlsProfile()
        return self._resolve(host, port, self._config)

    def reload(self) -> None:
        if self._config_path and self._config_path.exists():
            self._config = self._load(self._config_path)

    # ------------------------------------------------------------------
    # Internal loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load(path: Path) -> TlsConfig:
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load TLS config from {path}: {e}")
            return TlsConfig()

        # Build named profiles
        profiles: Dict[str, TlsProfile] = {}
        for name, pdata in (data.get("profiles") or {}).items():
            profiles[name] = TlsConfigLoader._parse_profile(pdata)

        # Default
        default_profile = TlsConfigLoader._parse_profile(data.get("default") or {})

        # Host overrides — order preserved (list of dicts or dict — support both)
        host_overrides: List[Tuple[str, TlsProfile]] = []
        raw_overrides = data.get("host_overrides") or {}
        # Support both YAML mapping (ordered in Python 3.7+) and list-of-single-key-dicts
        if isinstance(raw_overrides, dict):
            items = raw_overrides.items()
        else:
            items = ((list(d.keys())[0], list(d.values())[0]) for d in raw_overrides)

        for pattern, override_data in items:
            if isinstance(override_data, dict) and "profile" in override_data:
                profile_name = override_data["profile"]
                if profile_name not in profiles:
                    logger.warning(f"TLS host override references unknown profile '{profile_name}'")
                    continue
                host_overrides.append((str(pattern), profiles[profile_name]))
            else:
                host_overrides.append((str(pattern), TlsConfigLoader._parse_profile(override_data or {})))

        return TlsConfig(default=default_profile, profiles=profiles, host_overrides=host_overrides)

    @staticmethod
    def _parse_profile(data: Dict[str, Any]) -> TlsProfile:
        verify = data.get("verify", True)
        # YAML may give "true"/"false" strings — handle that
        if isinstance(verify, str):
            if verify.lower() == "false":
                verify = False
            elif verify.lower() == "true":
                verify = True
            # else: treat as CA-bundle path
        return TlsProfile(
            verify=verify,
            client_cert=data.get("client_cert"),
            client_key=data.get("client_key"),
            client_key_password_env=data.get("client_key_password_env"),
        )

    # ------------------------------------------------------------------
    # Host matching
    # ------------------------------------------------------------------

    @classmethod
    def _resolve(cls, host: str, port: Optional[int], config: TlsConfig) -> TlsProfile:
        """
        Return the first matching TlsProfile from host_overrides, or default.
        Matching priority (within the ordered list):
          1. Exact "host:port"
          2. Exact "host"
          3. Port-range "host_or_glob:start-end"
          4. Glob "host_pattern:port"
          5. Glob "host_pattern"
        The list is checked in the order it appears in the config file.
        """
        for pattern, profile in config.host_overrides:
            if cls._pattern_matches(pattern, host, port):
                return profile
        return config.default

    @staticmethod
    def _pattern_matches(pattern: str, host: str, port: Optional[int]) -> bool:
        """Check whether *pattern* matches *host* (and optional *port*)."""
        # Split pattern into host_part and port_part
        if ":" in pattern:
            # Could be "host:port", "host:start-end", "glob:port", "glob:start-end"
            # But be careful: IPv6 addresses contain colons. We treat the LAST colon as separator
            # when the right side is numeric or a range.
            last_colon = pattern.rfind(":")
            host_part = pattern[:last_colon]
            port_part = pattern[last_colon + 1:]
        else:
            host_part = pattern
            port_part = None

        # Match host
        host_match = fnmatch.fnmatch(host.lower(), host_part.lower())
        if not host_match:
            return False

        # Match port
        if port_part is None:
            # No port restriction — matches any port
            return True
        if port is None:
            # Pattern specifies a port, but we don't have one → no match
            return False
        if "-" in port_part:
            # Port range e.g. "8440-8449"
            try:
                lo, hi = port_part.split("-", 1)
                return int(lo) <= port <= int(hi)
            except ValueError:
                return False
        else:
            try:
                return port == int(port_part)
            except ValueError:
                return False

