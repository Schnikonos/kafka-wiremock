"""
DB Provider factory with auto-detection of available providers.

Built-in providers: oracle, mysql, cassandra
External providers: registered via register_external_provider() from user .py files
                     loaded from example/config/db_provider/.
"""
import logging
from typing import Any, Dict, Optional, Type

from .base import DBProvider

logger = logging.getLogger(__name__)


class DBProviderFactory:
    """
    Factory for creating DBProvider instances.

    Auto-detects which built-in libraries are installed on import.
    External providers can be registered at runtime via register_external_provider().
    """

    # provider_name → class
    _providers: Dict[str, Type[DBProvider]] = {}
    # provider_name → available (library present)
    _detected_providers: Dict[str, bool] = {}
    # flag: built-in detection has already run (separate from external registrations)
    _builtin_detection_done: bool = False

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @classmethod
    def _detect_providers(cls) -> None:
        """Auto-detect built-in providers based on installed libraries."""
        if cls._builtin_detection_done:
            return  # already done

        # Oracle
        try:
            import oracledb  # noqa: F401
            cls._detected_providers["oracle"] = True
            logger.info("Oracle provider available (oracledb)")
        except ImportError:
            try:
                import cx_Oracle  # noqa: F401
                cls._detected_providers["oracle"] = True
                logger.info("Oracle provider available (cx_Oracle)")
            except ImportError:
                cls._detected_providers["oracle"] = False
                logger.debug("Oracle provider not available (install oracledb or cx_Oracle)")

        # MySQL
        try:
            import mysql.connector  # noqa: F401
            cls._detected_providers["mysql"] = True
            logger.info("MySQL provider available (mysql-connector-python)")
        except ImportError:
            cls._detected_providers["mysql"] = False
            logger.debug("MySQL provider not available (install mysql-connector-python)")

        # Cassandra
        try:
            import cassandra  # noqa: F401
            cls._detected_providers["cassandra"] = True
            logger.info("Cassandra provider available (cassandra-driver)")
        except ImportError:
            cls._detected_providers["cassandra"] = False
            logger.debug("Cassandra provider not available (install cassandra-driver)")

        cls._builtin_detection_done = True
        available = [p for p, ok in cls._detected_providers.items() if ok]
        logger.info(
            f"DB available providers: {', '.join(available) or 'none (all built-ins missing)'}"
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    @classmethod
    def register_external_provider(cls, name: str, provider_class: Type[DBProvider]) -> None:
        """
        Register a custom DB provider.

        Called from user .py files in example/config/db_provider/:

            from src.db.providers.factory import DBProviderFactory
            DBProviderFactory.register_external_provider("my_db", MyDBProvider)

        Args:
            name:           Provider identifier used in databases.yaml ``provider`` field.
            provider_class: Class that inherits from DBProvider.
        """
        if not issubclass(provider_class, DBProvider):
            raise ValueError(f"Provider class must inherit from DBProvider, got {provider_class}")
        cls._providers[name] = provider_class
        cls._detected_providers[name] = True
        logger.info(f"External DB provider registered: '{name}' → {provider_class.__name__}")

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, provider_type: str, config: Dict[str, Any]) -> DBProvider:
        """
        Instantiate a provider.

        Args:
            provider_type: 'oracle' | 'mysql' | 'cassandra' | custom name
            config:        Dict of keyword args forwarded to the provider constructor.

        Returns:
            Connected DBProvider instance.

        Raises:
            ValueError: if provider_type is not available.
        """
        cls._detect_providers()

        if not cls._detected_providers.get(provider_type, False):
            available = [p for p, ok in cls._detected_providers.items() if ok]
            raise ValueError(
                f"DB provider '{provider_type}' not available. "
                f"Available: {', '.join(available) or 'none'}. "
                f"Install hint: {cls._install_hint(provider_type)}"
            )

        # Lazy-load built-in provider classes
        if provider_type not in cls._providers:
            cls._load_builtin(provider_type)

        provider_class = cls._providers.get(provider_type)
        if not provider_class:
            raise ValueError(f"DB provider '{provider_type}' registered but class not found")

        try:
            instance = provider_class(**config)
            logger.info(f"DB provider '{provider_type}' instantiated")
            return instance
        except Exception as e:
            logger.error(f"Failed to instantiate DB provider '{provider_type}': {e}")
            raise

    @classmethod
    def _load_builtin(cls, provider_type: str) -> None:
        if provider_type == "oracle":
            from .oracle import OracleDBProvider
            cls._providers["oracle"] = OracleDBProvider
        elif provider_type == "mysql":
            from .mysql import MySQLDBProvider
            cls._providers["mysql"] = MySQLDBProvider
        elif provider_type == "cassandra":
            from .cassandra import CassandraDBProvider
            cls._providers["cassandra"] = CassandraDBProvider
        else:
            raise ValueError(
                f"Unknown built-in provider '{provider_type}'. "
                f"Register custom providers via DBProviderFactory.register_external_provider()."
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @classmethod
    def get_available_providers(cls) -> Dict[str, Dict[str, Any]]:
        """Return metadata about all known providers."""
        cls._detect_providers()
        info: Dict[str, Dict[str, Any]] = {
            "oracle": {
                "available": cls._detected_providers.get("oracle", False),
                "library": "oracledb (or cx_Oracle)",
                "install_command": "pip install oracledb",
                "description": "Oracle Database — thin-mode driver, no Oracle Client needed",
                "config_fields": ["host", "port", "service_name", "username", "password", "ssl"],
            },
            "mysql": {
                "available": cls._detected_providers.get("mysql", False),
                "library": "mysql-connector-python",
                "install_command": "pip install mysql-connector-python",
                "description": "MySQL / MariaDB",
                "config_fields": ["host", "port", "database", "username", "password", "ssl"],
            },
            "cassandra": {
                "available": cls._detected_providers.get("cassandra", False),
                "library": "cassandra-driver",
                "install_command": "pip install cassandra-driver",
                "description": "Apache Cassandra / ScyllaDB",
                "config_fields": ["contact_points", "port", "keyspace", "username", "password", "ssl"],
            },
        }
        # Include any registered external providers
        for name, ok in cls._detected_providers.items():
            if name not in info:
                info[name] = {
                    "available": ok,
                    "library": "custom",
                    "install_command": "",
                    "description": f"Custom provider: {name}",
                    "config_fields": [],
                }
        return info

    @staticmethod
    def _install_hint(provider_type: str) -> str:
        hints = {
            "oracle": "pip install oracledb",
            "mysql": "pip install mysql-connector-python",
            "cassandra": "pip install cassandra-driver",
        }
        return hints.get(provider_type, f"pip install {provider_type}")

