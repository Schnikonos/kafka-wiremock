"""JMS configuration loader - loads jms-config YAML files."""
import logging
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from .jms_config import JMSConfig

logger = logging.getLogger(__name__)


class JMSConfigLoader:
    """Loads and manages JMS configuration from YAML files."""

    def __init__(self, config_dir: str = "/config"):
        """
        Initialize JMS config loader.

        Args:
            config_dir: Root configuration directory
        """
        self.config_dir = Path(config_dir)
        self.jms_config_dir = self.config_dir / "jms-config"
        self.configs: Dict[str, JMSConfig] = {}
        self.reload()

    def reload(self) -> None:
        """Reload JMS configurations from disk."""
        self.configs.clear()

        if not self.jms_config_dir.exists():
            logger.info(f"JMS config directory does not exist: {self.jms_config_dir}")
            return

        try:
            # Recursively find all .yaml files
            yaml_files = list(self.jms_config_dir.rglob("*.yaml")) + list(
                self.jms_config_dir.rglob("*.yml")
            )

            logger.info(f"Found {len(yaml_files)} JMS config files")

            for yaml_file in sorted(yaml_files):
                try:
                    configs = self._parse_jms_config_file(yaml_file)
                    self.configs.update(
                        {config.destination: config for config in configs}
                    )
                    logger.info(
                        f"Loaded {len(configs)} destination(s) from {yaml_file.relative_to(self.config_dir)}"
                    )
                except Exception as e:
                    logger.error(f"Error loading JMS config from {yaml_file}: {e}")

            logger.info(f"Loaded {len(self.configs)} total JMS destinations")

        except Exception as e:
            logger.error(f"Error scanning JMS config directory: {e}")

    def _parse_jms_config_file(self, yaml_file: Path) -> List[JMSConfig]:
        """Parse a single JMS config YAML file (may contain multiple documents)."""
        configs = []

        try:
            with open(yaml_file, "r") as f:
                documents = yaml.safe_load_all(f)

                for doc_idx, data in enumerate(documents):
                    if data is None:
                        continue

                    if not isinstance(data, dict):
                        logger.warning(
                            f"Document {doc_idx} in {yaml_file}: Expected dict, got {type(data).__name__}"
                        )
                        continue

                    if "destination" not in data and "queue" not in data:
                        logger.warning(
                            f"Document {doc_idx} in {yaml_file}: Missing 'destination' or 'queue' field"
                        )
                        continue

                    # Support both 'destination' and 'queue' field names
                    destination = data.get("destination") or data.get("queue")
                    destination_type = data.get("destination_type", "queue")
                    message_format = data.get("message", {}).get("format", "json")
                    jms_properties = data.get("jms_properties")
                    correlation = data.get("correlation")
                    queue_manager_ref = data.get("queue_manager_ref", "default")  # NEW
                    provider = data.get("provider", "ibm_mq")  # NEW

                    config = JMSConfig(
                        destination=destination,
                        queue_manager_ref=queue_manager_ref,  # NEW
                        provider=provider,  # NEW
                        destination_type=destination_type,
                        message_format=message_format,
                        jms_properties=jms_properties,
                        correlation=correlation,
                    )
                    configs.append(config)

        except Exception as e:
            logger.error(f"Error parsing JMS config file {yaml_file}: {e}")

        return configs

    def get_config(self, destination: str) -> Optional[JMSConfig]:
        """Get JMS config for a destination."""
        return self.configs.get(destination)

    def get_all_configs(self) -> Dict[str, JMSConfig]:
        """Get all JMS configurations."""
        return self.configs.copy()

    def has_config(self, destination: str) -> bool:
        """Check if JMS config exists for destination."""
        return destination in self.configs

