"""
Queue Manager configuration loader for multi-QM JMS support.
"""
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class QueueManagerConfig:
    """Configuration for a single queue manager."""

    name: str
    provider: str
    broker_url: str
    channel: str
    queue_manager: str
    username: str
    password: Optional[str] = None

    @staticmethod
    def resolve_env_variables(value: Optional[str]) -> Optional[str]:
        """
        Resolve ${VAR_NAME} syntax to environment variables.

        Args:
            value: String that may contain ${VAR_NAME} patterns

        Returns:
            Resolved string with environment variables substituted
        """
        if not value:
            return value

        pattern = r"\$\{([^}]+)\}"

        def replacer(match):
            env_var = match.group(1)
            result = os.getenv(env_var)
            if result is None:
                logger.warning(
                    f"Environment variable not found: {env_var}. "
                    f"Keeping placeholder ${{{env_var}}}"
                )
                return f"${{{env_var}}}"
            return result

        return re.sub(pattern, replacer, str(value))

    @classmethod
    def from_dict(cls, name: str, config_dict: Dict) -> "QueueManagerConfig":
        """
        Create QueueManagerConfig from dictionary.

        Args:
            name: Queue manager reference name
            config_dict: Configuration dictionary

        Returns:
            QueueManagerConfig instance
        """
        # Resolve environment variable references in YAML values
        broker_url = cls.resolve_env_variables(config_dict.get("broker_url"))
        username = cls.resolve_env_variables(config_dict.get("username"))

        # Get password from environment variable.
        # Format: JMS_{QM_NAME_UPPERCASE}_PASSWORD
        # e.g. qm_dev_local → JMS_QM_DEV_LOCAL_PASSWORD
        password_env_var = f"JMS_{name.upper()}_PASSWORD"
        password = os.getenv(password_env_var)

        if username and not password:
            logger.warning(
                f"Queue manager '{name}' has a username ('{username}') but no password. "
                f"Set the {password_env_var} environment variable. "
                f"Connection will likely fail."
            )

        return cls(
            name=name,
            provider=config_dict.get("provider", "ibm_mq"),
            broker_url=broker_url,
            channel=config_dict.get("channel", "DEV.APP.SVRCONN"),
            queue_manager=config_dict.get("queue_manager", "QM1"),
            username=username or "",
            password=password,
        )


class QueueManagerConfigLoader:
    """Loads queue manager configurations from queue-managers.yaml file."""

    def __init__(self, config_dir: str):
        """
        Initialize loader.

        Args:
            config_dir: Root configuration directory
        """
        self.config_dir = Path(config_dir)
        self.qm_file = self.config_dir / "jms-config" / "queue-managers.yaml"

    def load(self) -> Dict[str, QueueManagerConfig]:
        """
        Load queue manager configurations from queue-managers.yaml.

        Returns:
            Dictionary of queue manager name -> QueueManagerConfig
        """
        if not self.qm_file.exists():
            logger.info(f"Queue manager config not found: {self.qm_file}")
            return {}

        try:
            with open(self.qm_file) as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Error reading queue-managers.yaml: {e}")
            return {}

        configs = {}
        for qm_name, qm_data in data.get("queue_managers", {}).items():
            try:
                config = QueueManagerConfig.from_dict(qm_name, qm_data)
                configs[qm_name] = config
                logger.info(
                    f"Loaded queue manager config: {qm_name} "
                    f"(provider={config.provider}, qm={config.queue_manager})"
                )
            except Exception as e:
                logger.error(f"Error loading QM {qm_name}: {e}")

        if configs:
            logger.info(f"Loaded {len(configs)} queue manager(s)")
        else:
            logger.warning("No queue managers configured in queue-managers.yaml")

        return configs

