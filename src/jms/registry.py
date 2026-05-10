"""
JMS Client Registry for managing multiple queue manager connections with pooling.
"""
import logging
from typing import Dict, Optional, Callable
from .pool import JMSConnectionPool, PoolConfig  # NEW
from .providers.factory import ProviderFactory  # NEW: provider factory

logger = logging.getLogger(__name__)


class JMSClientRegistry:
    """Manages multiple JMS clients with connection pooling for different queue managers."""

    def __init__(self, enable_pooling: bool = True, pool_config: Optional[PoolConfig] = None):
        """
        Initialize registry with optional connection pooling.

        Args:
            enable_pooling: Enable connection pooling (default: True)
            pool_config: Configuration for connection pools
        """
        self.clients: Dict[str, 'JMSClient'] = {}
        self.pools: Dict[str, JMSConnectionPool] = {}  # NEW: connection pools
        self.client_configs: Dict[str, Dict] = {}  # NEW: store config for each client
        self._default_client_name: Optional[str] = None
        self.enable_pooling = enable_pooling  # NEW
        self.pool_config = pool_config or PoolConfig()  # NEW
        logger.info(f"JMSClientRegistry initialized with pooling={'enabled' if enable_pooling else 'disabled'}")

    def add_queue_manager(self, name: str, client: 'JMSClient', config: Optional[Dict] = None) -> None:
        """
        Register a JMS client for a queue manager.

        Args:
            name: Queue manager reference name (e.g., 'qm_us_east')
            client: JMS client instance
            config: Optional configuration dict for this client
        """
        self.clients[name] = client
        if config:
            self.client_configs[name] = config

        # NEW: Create connection pool for this queue manager if pooling enabled
        if self.enable_pooling:
            try:
                # Create factory function for this client
                def client_factory(c=client):
                    # Reconnect if needed
                    try:
                        if hasattr(c, 'connect') and not c.is_connected():
                            c.connect()
                    except Exception as e:
                        logger.debug(f"Reconnect attempt for {name}: {e}")
                    return c

                pool = JMSConnectionPool(
                    client_factory=client_factory,
                    config=self.pool_config,
                    qm_name=name
                )
                self.pools[name] = pool
                logger.info(f"Created connection pool for queue manager: {name}")
            except Exception as e:
                logger.warning(f"Failed to create connection pool for {name}: {e}")
                # Fallback to non-pooled client
                self.pools[name] = None

        if self._default_client_name is None:
            self._default_client_name = name
        logger.debug(f"Registered JMS client: {name}")

    def get_client(self, queue_manager_ref: Optional[str] = None) -> 'JMSClient':
        """
        Get client for specific queue manager, or default.

        Args:
            queue_manager_ref: Queue manager reference name
                             If None, returns default client

        Returns:
            JMS client instance

        Raises:
            ValueError: If queue manager not found and no default available
        """
        if queue_manager_ref and queue_manager_ref in self.clients:
            logger.debug(f"Getting client for QM: {queue_manager_ref}")
            return self.clients[queue_manager_ref]

        if self._default_client_name:
            logger.debug(f"Using default client: {self._default_client_name}")
            return self.clients[self._default_client_name]

        raise ValueError(
            "No JMS clients registered. Configure queue_managers.yaml and set JMS_QM_*_PASSWORD environment variables"
        )

    def get_all_clients(self) -> Dict[str, 'JMSClient']:
        """Get all registered clients."""
        return self.clients.copy()

    def close_all(self) -> None:
        """Close all client connections gracefully."""
        # NEW: Close all connection pools first
        for qm_name, pool in self.pools.items():
            if pool:
                try:
                    pool.close()
                    logger.info(f"Closed connection pool for {qm_name}")
                except Exception as e:
                    logger.warning(f"Error closing pool for {qm_name}: {e}")

        self.pools.clear()

        for qm_name, client in self.clients.items():
            try:
                client.close()
                logger.info(f"Closed JMS client for {qm_name}")
            except Exception as e:
                logger.warning(f"Error closing JMS client for {qm_name}: {e}")

    def is_empty(self) -> bool:
        """Check if registry has no clients."""
        return len(self.clients) == 0

    def get_pool_stats(self) -> Dict:
        """
        Get connection pool statistics for all queue managers.

        Returns:
            Dictionary mapping QM names to pool statistics
        """
        stats = {}
        for qm_name, pool in self.pools.items():
            if pool:
                try:
                    stats[qm_name] = {
                        "available": getattr(pool, '_available_count', 0),
                        "in_use": getattr(pool, '_in_use_count', 0),
                        "total": getattr(pool, '_size', 0),
                        "max_size": getattr(pool.config, 'max_size', 5) if hasattr(pool, 'config') else 5
                    }
                except Exception as e:
                    logger.debug(f"Failed to get pool stats for {qm_name}: {e}")
        return stats

    def enable_pooling_for(self, qm_name: str, config: Optional[PoolConfig] = None) -> bool:
        """
        Enable connection pooling for a specific queue manager. (NEW)

        Args:
            qm_name: Queue manager name
            config: Optional pool configuration

        Returns:
            True if pooling enabled, False otherwise
        """
        if qm_name not in self.clients:
            logger.warning(f"Queue manager {qm_name} not found")
            return False

        if qm_name in self.pools and self.pools[qm_name]:
            logger.info(f"Connection pooling already active for {qm_name}")
            return True

        try:
            client = self.clients[qm_name]
            # ...existing code...
            def client_factory():
                try:
                    if hasattr(client, 'connect') and not client.is_connected():
                        client.connect()
                except Exception as e:
                    logger.debug(f"Reconnect attempt for {qm_name}: {e}")
                return client

            pool = JMSConnectionPool(
                client_factory=client_factory,
                config=config or self.pool_config,
                qm_name=qm_name
            )
            self.pools[qm_name] = pool
            logger.info(f"Enabled connection pooling for {qm_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to enable pooling for {qm_name}: {e}")
            return False

    def get_available_providers(self) -> Dict:
        """
        Get information about available JMS providers. (NEW)

        Returns:
            Dictionary with provider information
        """
        return ProviderFactory.get_available_providers()

    def get_queue_manager_info(self, qm_name: Optional[str] = None) -> Dict:
        """
        Get information about registered queue managers. (NEW)

        Args:
            qm_name: Specific queue manager name (None for all)

        Returns:
            Dictionary with queue manager details
        """
        if qm_name:
            if qm_name not in self.clients:
                return {"error": f"Queue manager {qm_name} not found"}

            client = self.clients[qm_name]
            config = self.client_configs.get(qm_name, {})

            return {
                "name": qm_name,
                "provider": getattr(client, 'get_provider_type', lambda: 'unknown')(),
                "connected": client.is_connected() if hasattr(client, 'is_connected') else False,
                "config": {k: v for k, v in config.items() if k != 'password'}  # Redact password
            }
        else:
            # Return all queue managers
            result = {}
            for name, client in self.clients.items():
                config = self.client_configs.get(name, {})
                result[name] = {
                    "provider": getattr(client, 'get_provider_type', lambda: 'unknown')(),
                    "connected": client.is_connected() if hasattr(client, 'is_connected') else False,
                    "config": {k: v for k, v in config.items() if k != 'password'}
                }
            return result

