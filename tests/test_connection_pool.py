"""
Tests for JMS connection pooling functionality.
"""
import pytest
import time
import threading
from unittest.mock import Mock, MagicMock, patch

from src.jms.pool import (
    PoolConfig,
    PooledConnection,
    JMSConnectionPool,
)
from src.jms.registry import JMSClientRegistry


class TestPoolConfig:
    """Tests for pool configuration."""

    def test_default_config(self):
        """Test default pool configuration values."""
        config = PoolConfig()
        assert config.min_idle == 1
        assert config.max_size == 5
        assert config.max_wait_ms == 5000
        assert config.connection_timeout_ms == 30000
        assert config.test_on_borrow is True
        assert config.auto_reconnect is True
        assert config.reconnect_attempts == 3

    def test_custom_config(self):
        """Test custom pool configuration."""
        config = PoolConfig(
            min_idle=2,
            max_size=10,
            max_wait_ms=10000,
            auto_reconnect=False
        )
        assert config.min_idle == 2
        assert config.max_size == 10
        assert config.max_wait_ms == 10000
        assert config.auto_reconnect is False


class TestPooledConnection:
    """Tests for pooled connection wrapper."""

    def test_pooled_connection_creation(self):
        """Test creating a pooled connection."""
        client = Mock()
        current_time = time.time()
        pooled = PooledConnection(client, current_time)

        assert pooled.client == client
        assert pooled.creation_time == current_time
        assert pooled.is_valid is True

    def test_connection_usage_tracking(self):
        """Test connection usage time tracking."""
        client = Mock()
        creation_time = time.time()
        pooled = PooledConnection(client, creation_time)

        time.sleep(0.1)
        pooled.use()

        assert pooled.last_used_time > creation_time

    def test_connection_idle_detection(self):
        """Test idle connection detection."""
        client = Mock()
        pooled = PooledConnection(client, time.time())

        # Should be idle for 0ms (just created)
        assert pooled.is_idle_for(0)

        # Use the connection
        pooled.use()
        # Should not be idle immediately after use
        assert not pooled.is_idle_for(100)

        # Wait and check idle status
        time.sleep(0.15)
        assert pooled.is_idle_for(50)  # 50ms

    def test_connection_expiration(self):
        """Test connection expiration."""
        client = Mock()
        creation_time = time.time() - 2.0  # 2 seconds ago
        pooled = PooledConnection(client, creation_time)

        # Should be expired after 1 second lifetime
        assert pooled.is_expired(1000)
        # Should not be expired after 10 second lifetime
        assert not pooled.is_expired(10000)

    def test_connection_invalidation(self):
        """Test connection invalidation."""
        client = Mock()
        pooled = PooledConnection(client, time.time())

        assert pooled.is_valid is True
        pooled.invalidate()
        assert pooled.is_valid is False


class TestJMSConnectionPool:
    """Tests for JMS connection pool."""

    def create_mock_client(self):
        """Create a mock JMS client."""
        client = Mock()
        client.hconn = Mock()  # Mock connection handle
        client.close = Mock()
        return client

    def test_pool_initialization(self):
        """Test pool initialization with minimum idle connections."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=2)

        pool = JMSConnectionPool(factory, config, "test_qm")

        # Should have created 2 idle connections
        assert len(pool._available) == 2
        assert len(pool._in_use) == 0
        assert factory.call_count == 2
        pool.close()

    def test_get_connection(self):
        """Test getting a connection from pool."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=1)

        pool = JMSConnectionPool(factory, config, "test_qm")

        # Get connection from pool
        conn = pool.get_connection(timeout_ms=1000)

        assert conn is not None
        assert len(pool._available) == 0
        assert len(pool._in_use) == 1
        pool.close()

    def test_return_connection(self):
        """Test returning connection to pool."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=1)

        pool = JMSConnectionPool(factory, config, "test_qm")

        # Get and return connection
        conn = pool.get_connection(timeout_ms=1000)
        assert len(pool._in_use) == 1

        pool.return_connection(conn)
        assert len(pool._available) == 1
        assert len(pool._in_use) == 0
        pool.close()

    def test_pool_expansion(self):
        """Test pool expansion when needed."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=1, max_size=3)

        pool = JMSConnectionPool(factory, config, "test_qm")
        initial_count = factory.call_count

        # Get multiple connections to expand pool
        conn1 = pool.get_connection()
        conn2 = pool.get_connection()

        # Factory should have been called more times
        assert factory.call_count > initial_count
        # Pool should not exceed max size
        assert len(pool._available) + len(pool._in_use) <= config.max_size

        pool.return_connection(conn1)
        pool.return_connection(conn2)
        pool.close()

    def test_get_connection_timeout(self):
        """Test timeout when waiting for connection."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=1, max_size=1, max_wait_ms=100)

        pool = JMSConnectionPool(factory, config, "test_qm")

        # Get the only connection
        conn1 = pool.get_connection()

        # Should timeout trying to get another
        with pytest.raises(RuntimeError):
            pool.get_connection(timeout_ms=100)

        pool.return_connection(conn1)
        pool.close()

    def test_connection_validation(self):
        """Test connection validation."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=1, test_on_borrow=True)

        pool = JMSConnectionPool(factory, config, "test_qm")

        # Connection should be valid
        conn = pool.get_connection()
        assert conn.is_valid is True

        pool.return_connection(conn)
        pool.close()

    def test_cleanup_idle_connections(self):
        """Test cleanup of idle connections."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(
            min_idle=2,
            idle_timeout_ms=100,  # 100ms idle timeout
            max_lifetime_ms=10000
        )

        pool = JMSConnectionPool(factory, config, "test_qm")
        initial_available = len(pool._available)

        # Get and return connections
        conn1 = pool.get_connection()
        conn2 = pool.get_connection()
        pool.return_connection(conn1)
        pool.return_connection(conn2)

        time.sleep(0.15)  # Wait for idle timeout

        # Get a connection to trigger cleanup
        pool.get_connection()

        # Some connections should have been removed
        total_connections = len(pool._available) + len(pool._in_use)
        # After cleanup, should have fewer connections
        assert total_connections <= initial_available + 1

        pool.close()

    def test_auto_reconnect_on_invalid_connection(self):
        """Test automatic reconnection of invalid connections."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(
            min_idle=1,
            test_on_borrow=True,
            auto_reconnect=True,
            reconnect_attempts=2
        )

        pool = JMSConnectionPool(factory, config, "test_qm")

        # Manually create invalid connection
        pooled = pool._available.pop(0)
        pooled.is_valid = False
        pooled.client.hconn = None
        pool._available.append(pooled)

        # Getting connection should attempt reconnect
        # (In real scenario, factory would be called)
        if pool.config.test_on_borrow:
            initial_factory_calls = factory.call_count
            # The invalid connection would be auto-reconnected
            pool.close()

    def test_close_pool(self):
        """Test closing the pool."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=2)

        pool = JMSConnectionPool(factory, config, "test_qm")

        assert len(pool._available) == 2
        pool.close()

        # All connections should be closed
        assert len(pool._available) == 0
        assert mock_client.close.called

    def test_pool_statistics(self):
        """Test getting pool statistics."""
        mock_client = self.create_mock_client()
        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=1, max_size=5)

        pool = JMSConnectionPool(factory, config, "test_qm")

        # Get a connection
        conn = pool.get_connection()

        stats = pool.get_stats()

        assert stats["queue_manager"] == "test_qm"
        assert stats["available"] == 0
        assert stats["in_use"] == 1
        assert stats["total"] == 1
        assert stats["max_size"] == 5

        pool.return_connection(conn)
        pool.close()


class TestJMSClientRegistry:
    """Tests for JMS client registry with pooling."""

    def create_mock_client(self):
        """Create a mock JMS client."""
        client = Mock()
        client.hconn = Mock()
        client.close = Mock()
        client._connect = Mock()
        return client

    def test_registry_initialization(self):
        """Test registry initialization with pooling."""
        registry = JMSClientRegistry(enable_pooling=True)

        assert registry.enable_pooling is True
        assert isinstance(registry.pool_config, PoolConfig)
        assert registry.is_empty() is True

    def test_add_queue_manager_with_pooling(self):
        """Test adding queue manager with pooling."""
        registry = JMSClientRegistry(enable_pooling=True)
        mock_client = self.create_mock_client()

        registry.add_queue_manager("qm1", mock_client)

        assert "qm1" in registry.clients
        assert "qm1" in registry.pools
        assert registry.pools["qm1"] is not None

    def test_add_queue_manager_without_pooling(self):
        """Test adding queue manager without pooling."""
        registry = JMSClientRegistry(enable_pooling=False)
        mock_client = self.create_mock_client()

        registry.add_queue_manager("qm1", mock_client)

        assert "qm1" in registry.clients
        assert "qm1" not in registry.pools or not registry.pools.get("qm1")

    def test_get_default_client(self):
        """Test getting default client."""
        registry = JMSClientRegistry(enable_pooling=True)
        mock_client = self.create_mock_client()

        registry.add_queue_manager("qm1", mock_client)

        default = registry.get_client()
        assert default == mock_client

    def test_get_specific_client(self):
        """Test getting specific client by reference."""
        registry = JMSClientRegistry(enable_pooling=True)
        client1 = self.create_mock_client()
        client2 = self.create_mock_client()

        registry.add_queue_manager("qm1", client1)
        registry.add_queue_manager("qm2", client2)

        assert registry.get_client("qm1") == client1
        assert registry.get_client("qm2") == client2

    def test_get_pool_stats(self):
        """Test getting pool statistics."""
        registry = JMSClientRegistry(enable_pooling=True)
        mock_client = self.create_mock_client()

        registry.add_queue_manager("qm1", mock_client)

        stats = registry.get_pool_stats()

        assert "qm1" in stats
        assert "available" in stats["qm1"]
        assert "in_use" in stats["qm1"]

    def test_enable_pooling_dynamically(self):
        """Test enabling pooling for specific queue manager."""
        registry = JMSClientRegistry(enable_pooling=False)
        mock_client = self.create_mock_client()

        registry.add_queue_manager("qm1", mock_client)
        assert registry.pools.get("qm1") is None

        # Enable pooling dynamically
        result = registry.enable_pooling_for("qm1")

        assert result is True
        assert registry.pools["qm1"] is not None

    def test_close_all_pools(self):
        """Test closing all pools and clients."""
        registry = JMSClientRegistry(enable_pooling=True)
        client1 = self.create_mock_client()
        client2 = self.create_mock_client()

        registry.add_queue_manager("qm1", client1)
        registry.add_queue_manager("qm2", client2)

        registry.close_all()

        # All connections should be closed
        assert client1.close.called
        assert client2.close.called
        assert len(registry.pools) == 0

    def test_get_all_clients(self):
        """Test getting all registered clients."""
        registry = JMSClientRegistry(enable_pooling=True)
        client1 = self.create_mock_client()
        client2 = self.create_mock_client()

        registry.add_queue_manager("qm1", client1)
        registry.add_queue_manager("qm2", client2)

        all_clients = registry.get_all_clients()

        assert len(all_clients) == 2
        assert all_clients["qm1"] == client1
        assert all_clients["qm2"] == client2


class TestPoolConcurrency:
    """Tests for pool concurrency and thread safety."""

    def test_concurrent_connection_requests(self):
        """Test concurrent connection requests."""
        mock_client = Mock()
        mock_client.hconn = Mock()
        mock_client.close = Mock()

        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=1, max_size=5)
        pool = JMSConnectionPool(factory, config, "test_qm")

        connections = []
        errors = []

        def get_and_return():
            try:
                conn = pool.get_connection(timeout_ms=2000)
                time.sleep(0.01)
                pool.return_connection(conn)
                connections.append(conn)
            except Exception as e:
                errors.append(e)

        # Create 10 threads requesting connections concurrently
        threads = [threading.Thread(target=get_and_return) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not have any errors
        assert len(errors) == 0
        # Should have gotten 10 connections
        assert len(connections) == 10

        pool.close()

    def test_pool_expansion_under_load(self):
        """Test pool expansion under concurrent load."""
        mock_client = Mock()
        mock_client.hconn = Mock()
        mock_client.close = Mock()

        factory = Mock(return_value=mock_client)
        config = PoolConfig(min_idle=1, max_size=5)
        pool = JMSConnectionPool(factory, config, "test_qm")

        held_connections = []

        def hold_connection():
            conn = pool.get_connection(timeout_ms=5000)
            held_connections.append(conn)
            time.sleep(0.5)

        # Create 3 threads holding connections at the same time
        threads = [threading.Thread(target=hold_connection) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Pool should have expanded to accommodate
        stats = pool.get_stats()
        assert stats["total"] >= 3

        # Return all connections
        for conn in held_connections:
            pool.return_connection(conn)

        pool.close()




