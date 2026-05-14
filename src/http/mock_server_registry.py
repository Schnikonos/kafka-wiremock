"""
HTTP Mock Server Registry — manages the set of running HttpMockServer instances.
"""
import logging
from typing import Dict, List, Optional

from ..config.mock_server_config import MockServerConfig
from ..http.mock_server import HttpMockServer

logger = logging.getLogger(__name__)


class HttpMockServerRegistry:
    """
    Holds a collection of HttpMockServer instances and provides unified
    start / stop / status operations.

    Mirrors the interface of JMSClientRegistry for consistency.
    """

    def __init__(self):
        self._servers: Dict[str, HttpMockServer] = {}  # name → server

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_server(self, server: HttpMockServer) -> None:
        name = server.config.name
        if name in self._servers:
            logger.warning(f"Mock server '{name}' already registered — replacing")
        self._servers[name] = server
        logger.debug(f"Registered mock server '{name}' on port {server.config.port}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_all(self) -> None:
        """Start all registered mock servers."""
        if not self._servers:
            logger.info("No HTTP mock servers configured")
            return
        for name, server in self._servers.items():
            try:
                server.start()
            except Exception as e:
                logger.error(f"Failed to start mock server '{name}': {e}")

    def stop_all(self) -> None:
        """Stop all registered mock servers."""
        for name, server in self._servers.items():
            try:
                server.stop()
            except Exception as e:
                logger.warning(f"Error stopping mock server '{name}': {e}")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def is_empty(self) -> bool:
        return len(self._servers) == 0

    def get_server(self, name: str) -> Optional[HttpMockServer]:
        return self._servers.get(name)

    def get_server_info(self) -> List[Dict]:
        """Return a list of status dicts for the health endpoint."""
        results = []
        for name, server in self._servers.items():
            results.append({
                "name": name,
                "port": server.config.port,
                "tls": server.config.tls is not None,
                "running": server.is_running(),
            })
        return results

    def server_names(self) -> List[str]:
        return list(self._servers.keys())

