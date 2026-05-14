"""
Mock HTTP Server configuration loader.

Each mock server is declared in its own YAML file under:
    config/http-config/mock-servers/<name>.yaml

Example file (api-server.yaml):
    name: api-server
    port: 8081
    tls:                        # Optional — enables HTTPS on the mock server
      cert: /certs/server.pem
      key:  /certs/server.key
      ca:   /certs/ca.pem       # Optional — for mTLS client verification
    default_response:
      status_code: 404
      payload: '{"error": "not found"}'
      headers:
        Content-Type: application/json
    endpoints:                  # Optional endpoint-level overrides (before server default)
      - path: /health
        method: GET
        response:
          status_code: 200
          payload: '{"status": "healthy"}'
"""
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper — ${ENV_VAR} resolution
# ---------------------------------------------------------------------------

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_env(value: Optional[str]) -> Optional[str]:
    """Replace ``${VAR}`` tokens with environment variable values."""
    if not value:
        return value

    def _replace(m: re.Match) -> str:
        var = m.group(1)
        result = os.getenv(var)
        if result is None:
            logger.warning(f"Environment variable '{var}' not found; keeping placeholder.")
            return f"${{{var}}}"
        return result

    return _ENV_PATTERN.sub(_replace, str(value))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MockServerTls:
    """TLS configuration for the mock server (inbound / server-side)."""
    cert: Optional[str] = None            # Path to server certificate PEM
    key: Optional[str] = None             # Path to server private key PEM
    ca: Optional[str] = None              # Path to CA bundle (enables mTLS client verification)
    key_password_env: Optional[str] = None  # Env-var that holds the key passphrase


@dataclass
class EndpointDefault:
    """A path-pattern level default response (lower priority than rules/stubs)."""
    path_pattern: str                     # e.g. "/orders/{orderId}" or "/health"
    method: str = "*"                     # HTTP method or "*" for any
    status_code: int = 200
    payload: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    content_type: str = "application/json"


@dataclass
class MockServerConfig:
    """Full configuration for one mock HTTP server."""
    name: str
    port: int
    tls: Optional[MockServerTls] = None
    # Server-level default response (lowest priority, used when nothing else matches)
    default_status_code: int = 404
    default_payload: Optional[str] = None
    default_headers: Dict[str, str] = field(default_factory=dict)
    default_content_type: str = "application/json"
    # Endpoint-level overrides (evaluated before server default, after rules)
    endpoints: List[EndpointDefault] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class MockServerConfigLoader:
    """
    Scans ``config/http-config/mock-servers/`` for ``*.yaml`` / ``*.yml``
    files and returns a mapping of server-name → MockServerConfig.
    """

    def __init__(self, config_dir: str = "/config"):
        self.config_dir = Path(config_dir)
        self._mock_servers_dir = self.config_dir / "http-config" / "mock-servers"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, MockServerConfig]:
        """
        Load all mock server configs from disk.

        Returns:
            Dict mapping server name → MockServerConfig.
            Empty dict if the directory does not exist.
        """
        configs: Dict[str, MockServerConfig] = {}

        if not self._mock_servers_dir.exists():
            logger.debug(
                f"Mock servers directory does not exist: {self._mock_servers_dir} — "
                f"no HTTP mock servers will be started."
            )
            return configs

        yaml_files = sorted(
            list(self._mock_servers_dir.rglob("*.yaml"))
            + list(self._mock_servers_dir.rglob("*.yml"))
        )

        if not yaml_files:
            logger.info(f"No mock server YAML files found in {self._mock_servers_dir}")
            return configs

        for yaml_file in yaml_files:
            try:
                cfg = self._parse_file(yaml_file)
                if cfg:
                    if cfg.name in configs:
                        logger.warning(
                            f"Duplicate mock server name '{cfg.name}' found in "
                            f"{yaml_file} — overwriting previous entry."
                        )
                    configs[cfg.name] = cfg
                    logger.info(
                        f"Loaded mock server '{cfg.name}' on port {cfg.port} "
                        f"from {yaml_file.name}"
                    )
            except Exception as e:
                logger.error(f"Failed to load mock server config from {yaml_file}: {e}")

        logger.info(f"Loaded {len(configs)} mock server(s)")
        return configs

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_file(self, yaml_file: Path) -> Optional[MockServerConfig]:
        with open(yaml_file, "r") as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data, dict):
            logger.warning(f"Empty or invalid mock server config: {yaml_file}")
            return None

        name = data.get("name") or yaml_file.stem
        port_raw = data.get("port")
        if port_raw is None:
            raise ValueError(f"'port' is required in mock server config: {yaml_file}")
        port = int(port_raw)

        # TLS
        tls: Optional[MockServerTls] = None
        if "tls" in data and data["tls"]:
            t = data["tls"]
            tls = MockServerTls(
                cert=_resolve_env(t.get("cert")),
                key=_resolve_env(t.get("key")),
                ca=_resolve_env(t.get("ca")),
                key_password_env=t.get("key_password_env"),
            )

        # Default response
        default_status = 404
        default_payload = None
        default_headers: Dict[str, str] = {}
        default_content_type = "application/json"
        if "default_response" in data and data["default_response"]:
            dr = data["default_response"]
            default_status = int(dr.get("status_code", 404))
            default_payload = dr.get("payload")
            default_headers = dr.get("headers") or {}
            default_content_type = dr.get("content_type", "application/json")

        # Endpoint-level defaults
        endpoints: List[EndpointDefault] = []
        for ep_raw in data.get("endpoints") or []:
            if not isinstance(ep_raw, dict):
                continue
            ep_path = ep_raw.get("path")
            if not ep_path:
                logger.warning(f"Endpoint entry missing 'path' in {yaml_file} — skipping")
                continue
            ep_method = ep_raw.get("method", "*")
            resp = ep_raw.get("response") or {}
            endpoints.append(EndpointDefault(
                path_pattern=ep_path,
                method=str(ep_method).upper() if ep_method != "*" else "*",
                status_code=int(resp.get("status_code", 200)),
                payload=resp.get("payload"),
                headers=resp.get("headers") or {},
                content_type=resp.get("content_type", "application/json"),
            ))

        return MockServerConfig(
            name=name,
            port=port,
            tls=tls,
            default_status_code=default_status,
            default_payload=default_payload,
            default_headers=default_headers,
            default_content_type=default_content_type,
            endpoints=endpoints,
        )

