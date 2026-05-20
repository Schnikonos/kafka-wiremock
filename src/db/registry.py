"""
DB Registry — manages named DBProvider instances with connection pools.
"""
import logging
from typing import Any, Dict, List, Optional

from .pool import DBConnectionPool
from .providers.base import DBProvider
from .providers.factory import DBProviderFactory

logger = logging.getLogger(__name__)


class DBRegistry:
    """
    Registry for named database connections with pooling.

    Each database defined in ``databases.yaml`` gets one entry here.
    Callers acquire a provider via get_provider(), use it, then release it.
    """

    def __init__(self):
        self._pools: Dict[str, DBConnectionPool] = {}
        self._configs: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_database(
        self,
        name: str,
        pool: DBConnectionPool,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a database connection pool.

        Args:
            name:   Logical name as defined in databases.yaml (e.g. 'onepam').
            pool:   Pre-created DBConnectionPool for this database.
            config: Original config dict (for status display; passwords redacted by caller).
        """
        self._pools[name] = pool
        self._configs[name] = config or {}
        logger.debug(f"Registered DB: '{name}'")

    # ------------------------------------------------------------------
    # Acquire / release
    # ------------------------------------------------------------------

    def get_provider(self, db_ref: str) -> DBProvider:
        """
        Acquire a provider from the named pool.

        Must be paired with release_provider() to avoid pool exhaustion.

        Raises:
            ValueError: if db_ref is not registered.
            TimeoutError: if no connection is available in time.
        """
        pool = self._pools.get(db_ref)
        if pool is None:
            known = ", ".join(self._pools.keys()) or "none"
            raise ValueError(
                f"DB '{db_ref}' not found in registry. "
                f"Configure it in databases.yaml. Known databases: {known}"
            )
        return pool.acquire()

    def release_provider(self, db_ref: str, provider: DBProvider) -> None:
        """Return a borrowed provider back to its pool."""
        pool = self._pools.get(db_ref)
        if pool:
            pool.release(provider)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_all_names(self) -> List[str]:
        return list(self._pools.keys())

    def is_empty(self) -> bool:
        return len(self._pools) == 0

    def get_status(self) -> Dict[str, Any]:
        """Return status dict for /api/db/status endpoint."""
        status: Dict[str, Any] = {}
        for name, pool in self._pools.items():
            cfg = self._configs.get(name, {})
            stats = pool.stats()
            status[name] = {
                "provider": cfg.get("provider", "unknown"),
                "host": cfg.get("host") or cfg.get("contact_points"),
                "pool": stats,
            }
        return status

    def get_available_providers(self) -> Dict[str, Any]:
        """Proxy to DBProviderFactory for API exposure."""
        return DBProviderFactory.get_available_providers()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def close_all(self) -> None:
        """Close all connection pools."""
        for name, pool in self._pools.items():
            try:
                pool.close()
                logger.info(f"DB pool '{name}' closed")
            except Exception as e:
                logger.warning(f"Error closing DB pool '{name}': {e}")
        self._pools.clear()

