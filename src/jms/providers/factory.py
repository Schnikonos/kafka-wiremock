"""
JMS Provider factory with auto-detection of available providers.
"""
import logging
from typing import Dict, Optional, Type, List, Any
from .base import JMSProvider

logger = logging.getLogger(__name__)


class ProviderFactory:
    """
    Factory for creating JMS provider instances with auto-detection.
    Supports option C (hybrid): auto-detects available providers and allows explicit override.
    """

    # Registry of available provider implementations
    _providers: Dict[str, Type[JMSProvider]] = {}
    _detected_providers: Dict[str, bool] = {}  # provider_name -> available

    @classmethod
    def _detect_providers(cls) -> None:
        """
        Auto-detect which JMS providers are available based on installed libraries.
        Called once at startup.
        """
        if cls._detected_providers:  # Already detected
            return

        # Try to import IBM MQ provider (uses pymqi - open source library on PyPI)
        try:
            import pymqi  # noqa: F401
            cls._detected_providers["ibm_mq"] = True
            logger.info("IBM MQ provider available (pymqi)")
        except ImportError:
            cls._detected_providers["ibm_mq"] = False
            logger.debug("IBM MQ provider not available (pymqi library not installed)")

        # Try to import ActiveMQ provider
        try:
            import stomp  # noqa: F401
            cls._detected_providers["activemq"] = True
            logger.info("ActiveMQ provider available")
        except ImportError:
            cls._detected_providers["activemq"] = False
            logger.debug("ActiveMQ provider not available (stomp library not installed)")

        # Try to import RabbitMQ provider
        try:
            import pika  # noqa: F401
            cls._detected_providers["rabbitmq"] = True
            logger.info("RabbitMQ provider available")
        except ImportError:
            cls._detected_providers["rabbitmq"] = False
            logger.debug("RabbitMQ provider not available (pika library not installed)")

        logger.info(
            f"Available providers: "
            f"{', '.join([p for p, avail in cls._detected_providers.items() if avail]) or 'none'}"
        )

    @classmethod
    def register_provider(cls, provider_name: str, provider_class: Type[JMSProvider]) -> None:
        """
        Register a provider implementation.

        Args:
            provider_name: Provider identifier (e.g., 'ibm_mq', 'activemq', 'rabbitmq')
            provider_class: Provider class (must inherit from JMSProvider)
        """
        if not issubclass(provider_class, JMSProvider):
            raise ValueError(f"Provider class must inherit from JMSProvider")
        cls._providers[provider_name] = provider_class
        logger.debug(f"Registered provider: {provider_name}")

    @classmethod
    def create(cls, provider_type: str, config: Dict[str, Any]) -> JMSProvider:
        """
        Create a JMS provider instance.

        Args:
            provider_type: Provider type (e.g., 'ibm_mq', 'activemq', 'rabbitmq')
            config: Provider-specific configuration dictionary

        Returns:
            Instance of the appropriate JMSProvider

        Raises:
            ValueError: If provider type not supported or not installed
        """
        # Ensure providers are detected
        cls._detect_providers()

        # Check if provider is available
        if not cls._detected_providers.get(provider_type, False):
            available = [p for p, avail in cls._detected_providers.items() if avail]
            raise ValueError(
                f"Provider '{provider_type}' not available. "
                f"Available providers: {', '.join(available) or 'none'}. "
                f"Install with: pip install {cls._get_install_command(provider_type)}"
            )

        # Lazy load and register provider if not already registered
        if provider_type not in cls._providers:
            cls._load_provider(provider_type)

        # Create instance
        provider_class = cls._providers.get(provider_type)
        if not provider_class:
            raise ValueError(f"Provider '{provider_type}' not found")

        try:
            instance = provider_class(**config)
            logger.info(f"Created {provider_type} provider instance")
            return instance
        except Exception as e:
            logger.error(f"Failed to create {provider_type} provider: {e}")
            raise

    @classmethod
    def _load_provider(cls, provider_type: str) -> None:
        """Lazy-load a provider implementation."""
        if provider_type == "ibm_mq":
            from .ibm_mq import IBMMQProvider
            cls.register_provider("ibm_mq", IBMMQProvider)
        elif provider_type == "activemq":
            from .activemq import ActiveMQProvider
            cls.register_provider("activemq", ActiveMQProvider)
        elif provider_type == "rabbitmq":
            from .rabbitmq import RabbitMQProvider
            cls.register_provider("rabbitmq", RabbitMQProvider)
        else:
            raise ValueError(f"Unknown provider type: {provider_type}")

    @classmethod
    def get_available_providers(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get information about available JMS providers.

        Returns:
            Dictionary mapping provider names to their info (available, install_cmd, etc.)
        """
        cls._detect_providers()
        return {
            "ibm_mq": {
                "available": cls._detected_providers.get("ibm_mq", False),
                "library": "pymqi",
                "install_command": "pip install pymqi==1.12.13",
                "description": "IBM MQ using pymqi (open-source, available on public PyPI)",
                "config_fields": ["broker_url", "channel", "queue_manager", "username"]
            },
            "activemq": {
                "available": cls._detected_providers.get("activemq", False),
                "library": "stomp.py",
                "install_command": "pip install stomp.py==8.1.0",
                "description": "Apache ActiveMQ with STOMP protocol",
                "config_fields": ["broker_url", "username", "password"]
            },
            "rabbitmq": {
                "available": cls._detected_providers.get("rabbitmq", False),
                "library": "pika",
                "install_command": "pip install pika==1.3.0",
                "description": "RabbitMQ with AMQP protocol",
                "config_fields": ["broker_url", "username", "password", "virtual_host"]
            }
        }

    @staticmethod
    def _get_install_command(provider_type: str) -> str:
        """Get pip install command for a provider."""
        commands = {
            "ibm_mq": "pymqi==1.12.13",
            "activemq": "stomp.py==8.1.0",
            "rabbitmq": "pika==1.3.0"
        }
        return commands.get(provider_type, provider_type)

