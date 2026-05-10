"""
Models for configuration data structures (provider-specific).
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class IBMMQConfig:
    """IBM MQ provider configuration."""
    provider: str = "ibm_mq"
    broker_url: str = ""
    channel: str = ""
    queue_manager: str = ""
    username: str = ""
    password: Optional[str] = None
    ssl_key_store: Optional[str] = None
    ssl_key_store_password: Optional[str] = None


@dataclass
class ActiveMQConfig:
    """ActiveMQ provider configuration."""
    provider: str = "activemq"
    broker_url: str = ""
    username: str = ""
    password: Optional[str] = None
    vhost: str = "/"


@dataclass
class RabbitMQConfig:
    """RabbitMQ provider configuration."""
    provider: str = "rabbitmq"
    broker_url: str = ""
    username: str = "guest"
    password: Optional[str] = None
    virtual_host: str = "/"


@dataclass
class PoolConfig:
    """Connection pool configuration."""
    min_idle: int = 1
    max_size: int = 5
    max_wait_ms: int = 5000
    idle_timeout_ms: int = 900000
    max_lifetime_ms: int = 1800000
    auto_reconnect: bool = True
    reconnect_attempts: int = 3
    reconnect_delay_ms: int = 1000


@dataclass
class QueueManagerConfig:
    """Complete queue manager configuration."""
    name: str
    provider: str
    broker_url: str
    username: str = ""
    password: Optional[str] = None
    channel: Optional[str] = None
    queue_manager: Optional[str] = None
    vhost: Optional[str] = None
    virtual_host: Optional[str] = None
    ssl_key_store: Optional[str] = None
    ssl_key_store_password: Optional[str] = None
    pool: Optional[PoolConfig] = None
    extra_config: Dict[str, Any] = field(default_factory=dict)

