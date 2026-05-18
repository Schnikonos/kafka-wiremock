"""
DB connection pool — simple thread-safe pool wrapping DBProvider instances.

Each pool holds a fixed number of DBProvider instances.  Callers acquire()
a provider, use it, then release() it back.  The pool is pre-warmed on first
acquire() (lazy connect).
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .providers.base import DBProvider

logger = logging.getLogger(__name__)


@dataclass
class DBPoolConfig:
    """Configuration for DBConnectionPool."""
    min_size: int = 1
    """Minimum number of connections to keep open at startup."""

    max_size: int = 5
    """Maximum simultaneous connections in the pool."""

    acquire_timeout_s: float = 10.0
    """Seconds to wait for a free connection before raising TimeoutError."""

    validate_on_borrow: bool = True
    """Call is_connected() before lending a connection; reconnect if needed."""


class DBConnectionPool:
    """
    Thread-safe connection pool for a single DBProvider type.

    provider_factory: callable() → DBProvider  (creates a new pre-connected instance)
    """

    def __init__(
        self,
        provider_factory: Callable[[], DBProvider],
        config: Optional[DBPoolConfig] = None,
        db_name: str = "unknown",
    ):
        self._factory = provider_factory
        self.config = config or DBPoolConfig()
        self._db_name = db_name

        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(self.config.max_size)
        self._available: List[DBProvider] = []  # idle connections
        self._in_use: List[DBProvider] = []

        # Pre-warm min_size connections
        for _ in range(self.config.min_size):
            try:
                provider = self._factory()
                with self._lock:
                    self._available.append(provider)
            except Exception as e:
                logger.warning(
                    f"[DBPool:{self._db_name}] Failed to pre-warm connection: {e}"
                )

    # ------------------------------------------------------------------
    # Acquire / release
    # ------------------------------------------------------------------

    def acquire(self) -> DBProvider:
        """
        Borrow a connection from the pool.

        Blocks up to ``config.acquire_timeout_s`` seconds.

        Raises:
            TimeoutError: if no connection becomes available in time.
            ConnectionError: if a new connection cannot be created.
        """
        acquired = self._semaphore.acquire(timeout=self.config.acquire_timeout_s)
        if not acquired:
            raise TimeoutError(
                f"[DBPool:{self._db_name}] Timed out waiting for a connection "
                f"(max_size={self.config.max_size}, "
                f"timeout={self.config.acquire_timeout_s}s)"
            )

        with self._lock:
            provider: Optional[DBProvider] = None

            # Try to reuse an idle connection
            while self._available:
                candidate = self._available.pop()
                if self.config.validate_on_borrow:
                    try:
                        if not candidate.is_connected():
                            candidate.connect()
                    except Exception as e:
                        logger.warning(
                            f"[DBPool:{self._db_name}] Stale connection discarded: {e}"
                        )
                        try:
                            candidate.disconnect()
                        except Exception:
                            pass
                        continue
                provider = candidate
                break

            # Create a new connection if none available
            if provider is None:
                try:
                    provider = self._factory()
                except Exception as e:
                    self._semaphore.release()
                    raise ConnectionError(
                        f"[DBPool:{self._db_name}] Failed to create new connection: {e}"
                    ) from e

            self._in_use.append(provider)
            return provider

    def release(self, provider: DBProvider) -> None:
        """Return a borrowed connection to the pool."""
        with self._lock:
            if provider in self._in_use:
                self._in_use.remove(provider)
            self._available.append(provider)
        self._semaphore.release()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        with self._lock:
            return {
                "available": len(self._available),
                "in_use": len(self._in_use),
                "max_size": self.config.max_size,
            }

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close all connections in the pool."""
        with self._lock:
            all_providers = list(self._available) + list(self._in_use)
            self._available.clear()
            self._in_use.clear()

        for provider in all_providers:
            try:
                provider.disconnect()
            except Exception as e:
                logger.warning(f"[DBPool:{self._db_name}] Error closing connection: {e}")

        logger.info(f"[DBPool:{self._db_name}] Pool closed ({len(all_providers)} connections)")

