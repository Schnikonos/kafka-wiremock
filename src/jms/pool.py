"""
Connection pooling for JMS clients with auto-reconnect support.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class PoolConfig:
    """Configuration for connection pool."""

    min_idle: int = 1  # Minimum idle connections
    max_size: int = 5  # Maximum connections in pool
    max_wait_ms: int = 5000  # Max wait time for connection
    connection_timeout_ms: int = 30000  # Connection timeout
    idle_timeout_ms: int = 900000  # 15 minutes idle timeout
    max_lifetime_ms: int = 1800000  # 30 minutes max lifetime
    test_on_borrow: bool = True  # Test connection when borrowed
    auto_reconnect: bool = True  # Auto-reconnect on failure
    reconnect_attempts: int = 3  # Number of reconnect attempts
    reconnect_delay_ms: int = 1000  # Delay between reconnect attempts


class PooledConnection:
    """Wrapper for a pooled connection with lifecycle tracking."""

    def __init__(self, client, creation_time: float):
        """
        Initialize pooled connection.

        Args:
            client: JMS client instance
            creation_time: Unix timestamp of creation
        """
        self.client = client
        self.creation_time = creation_time
        self.last_used_time = creation_time
        self.is_valid = True
        self._lock = threading.Lock()

    def use(self) -> None:
        """Mark connection as used."""
        with self._lock:
            self.last_used_time = time.time()

    def is_idle_for(self, duration_ms: int) -> bool:
        """Check if connection has been idle for specified duration."""
        idle_duration = (time.time() - self.last_used_time) * 1000
        return idle_duration >= duration_ms

    def is_expired(self, max_lifetime_ms: int) -> bool:
        """Check if connection has exceeded max lifetime."""
        lifetime = (time.time() - self.creation_time) * 1000
        return lifetime >= max_lifetime_ms

    def invalidate(self) -> None:
        """Mark connection as invalid."""
        with self._lock:
            self.is_valid = False


class JMSConnectionPool:
    """Connection pool for a single JMS client."""

    def __init__(
        self,
        client_factory: Callable,
        config: PoolConfig = None,
        qm_name: str = "default"
    ):
        """
        Initialize connection pool.

        Args:
            client_factory: Callable that creates JMS client instances
            config: Pool configuration
            qm_name: Queue manager name for logging
        """
        self.client_factory = client_factory
        self.config = config or PoolConfig()
        self.qm_name = qm_name

        self._available = []  # Available idle connections
        self._in_use = set()  # Currently borrowed connections
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)  # Condition variable for waiting
        self._closed = False

        # Initialize minimum idle connections
        self._initialize_idle_connections()

        logger.info(
            f"Connection pool created for {qm_name}: "
            f"min_idle={self.config.min_idle}, max_size={self.config.max_size}"
        )

    def _initialize_idle_connections(self) -> None:
        """Create minimum idle connections."""
        for _ in range(self.config.min_idle):
            try:
                client = self.client_factory()
                pooled = PooledConnection(client, time.time())
                self._available.append(pooled)
                logger.debug(f"Created idle connection for {self.qm_name}")
            except Exception as e:
                logger.warning(
                    f"Failed to create idle connection for {self.qm_name}: {e}"
                )

    def get_connection(self, timeout_ms: Optional[int] = None):
        """
        Get a connection from the pool.

        Args:
            timeout_ms: Timeout in milliseconds (None = use config default)

        Returns:
            PooledConnection instance

        Raises:
            RuntimeError: If no connection available and timeout exceeded
        """
        timeout_ms = timeout_ms or self.config.max_wait_ms
        timeout_sec = timeout_ms / 1000.0

        with self._cv:
            while True:
                # Clean up idle and expired connections
                self._cleanup_connections()

                # Try to get available connection
                if self._available:
                    pooled = self._available.pop(0)

                    # Validate connection if configured
                    if self.config.test_on_borrow:
                        if self._is_connection_valid(pooled):
                            self._in_use.add(pooled)
                            pooled.use()
                            return pooled
                        else:
                            # Connection invalid, try to reconnect
                            if self._reconnect(pooled):
                                self._in_use.add(pooled)
                                pooled.use()
                                return pooled
                            else:
                                continue  # Try next connection
                    else:
                        self._in_use.add(pooled)
                        pooled.use()
                        return pooled

                # Create new connection if below max size
                if len(self._in_use) + len(self._available) < self.config.max_size:
                    try:
                        client = self.client_factory()
                        pooled = PooledConnection(client, time.time())
                        self._in_use.add(pooled)
                        pooled.use()
                        logger.debug(f"Created new pooled connection for {self.qm_name}")
                        return pooled
                    except Exception as e:
                        logger.warning(
                            f"Failed to create new connection for {self.qm_name}: {e}"
                        )

                # Wait for available connection
                if not self._cv.wait(timeout=timeout_sec):
                    raise RuntimeError(
                        f"Timeout waiting for connection from pool {self.qm_name} "
                        f"after {timeout_ms}ms"
                    )

    def return_connection(self, pooled: PooledConnection) -> None:
        """
        Return connection to the pool.

        Args:
            pooled: PooledConnection to return
        """
        with self._cv:
            if pooled in self._in_use:
                self._in_use.remove(pooled)

            if pooled.is_valid:
                self._available.append(pooled)
                logger.debug(f"Returned connection to pool {self.qm_name}")
            else:
                # Connection was invalidated, don't return it
                logger.debug(f"Discarded invalid connection from pool {self.qm_name}")

            self._cv.notify()  # Wake up waiter

    def _cleanup_connections(self) -> None:
        """Remove idle and expired connections."""
        to_remove = []

        for pooled in self._available:
            if pooled.is_expired(self.config.max_lifetime_ms):
                to_remove.append(pooled)
                logger.debug(f"Removing expired connection from {self.qm_name}")
            elif pooled.is_idle_for(self.config.idle_timeout_ms):
                to_remove.append(pooled)
                logger.debug(f"Removing idle connection from {self.qm_name}")

        for pooled in to_remove:
            self._available.remove(pooled)
            try:
                pooled.client.close()
            except Exception as e:
                logger.debug(f"Error closing connection from {self.qm_name}: {e}")

    def _is_connection_valid(self, pooled: PooledConnection) -> bool:
        """
        Test if connection is still valid.

        Args:
            pooled: PooledConnection to test

        Returns:
            True if valid, False otherwise
        """
        try:
            # Simple test: check if client has basic methods
            if hasattr(pooled.client, 'hconn') and pooled.client.hconn:
                return True
            return False
        except Exception as e:
            logger.debug(f"Connection validation failed for {self.qm_name}: {e}")
            return False

    def _reconnect(self, pooled: PooledConnection) -> bool:
        """
        Attempt to reconnect a failed connection.

        Args:
            pooled: PooledConnection to reconnect

        Returns:
            True if reconnection successful, False otherwise
        """
        if not self.config.auto_reconnect:
            return False

        logger.info(f"Attempting to reconnect for {self.qm_name}")

        # Close old connection
        try:
            pooled.client.close()
        except Exception as e:
            logger.debug(f"Error closing old connection for {self.qm_name}: {e}")

        # Try to create new connection
        for attempt in range(self.config.reconnect_attempts):
            try:
                # Wait before retry (exponential backoff)
                if attempt > 0:
                    delay_ms = self.config.reconnect_delay_ms * (2 ** (attempt - 1))
                    time.sleep(delay_ms / 1000.0)

                new_client = self.client_factory()
                pooled.client = new_client
                pooled.is_valid = True
                logger.info(f"Reconnected successfully to {self.qm_name}")
                return True
            except Exception as e:
                logger.warning(
                    f"Reconnection attempt {attempt + 1} failed for {self.qm_name}: {e}"
                )

        pooled.invalidate()
        logger.error(f"Failed to reconnect to {self.qm_name} after {self.config.reconnect_attempts} attempts")
        return False

    def close(self) -> None:
        """Close all connections in pool."""
        with self._cv:
            self._closed = True

            # Close available connections
            for pooled in self._available:
                try:
                    pooled.client.close()
                except Exception as e:
                    logger.debug(f"Error closing pooled connection for {self.qm_name}: {e}")

            self._available.clear()
            logger.info(f"Connection pool closed for {self.qm_name}")

    def get_stats(self) -> Dict:
        """Get pool statistics."""
        with self._lock:
            return {
                "queue_manager": self.qm_name,
                "available": len(self._available),
                "in_use": len(self._in_use),
                "total": len(self._available) + len(self._in_use),
                "max_size": self.config.max_size
            }

