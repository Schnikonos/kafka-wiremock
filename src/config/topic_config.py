"""
Topic Configuration Management.
Loads and manages topic-specific settings (message format, correlation rules, schema registry, etc.)
from YAML files in config/topic-config/.
"""
import logging
import yaml
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class CorrelationExtractRule:
    """Rule for extracting correlation ID from a message."""
    from_type: str  # "header" or "jsonpath"
    name: Optional[str] = None  # Header name (for header type)
    expression: Optional[str] = None  # JSONPath expression (for jsonpath type)
    priority: int = 0  # Lower number = checked first

    def __post_init__(self):
        """Validate the rule."""
        if self.from_type not in ("header", "jsonpath"):
            raise ValueError(f"Invalid from_type: {self.from_type}")
        if self.from_type == "header" and not self.name:
            raise ValueError("Header type requires 'name' field")
        if self.from_type == "jsonpath" and not self.expression:
            raise ValueError("JSONPath type requires 'expression' field")


@dataclass
class CorrelationPropagateRule:
    """Rule for writing correlation ID to a message."""
    to_headers: Optional[Dict[str, str]] = None  # {header_name: template} - templates can use {{correlationId}}

    def __post_init__(self):
        """Validate the rule."""
        if not self.to_headers:
            self.to_headers = {}


@dataclass
class CorrelationConfig:
    """Correlation configuration for a topic."""
    extract: List[CorrelationExtractRule] = field(default_factory=list)  # Priority-ordered
    propagate: Optional[CorrelationPropagateRule] = None


@dataclass
class TopicConfig:
    """Configuration for a Kafka topic."""
    topic: str
    message_format: str = "json"  # json, avro, text, bytes
    schema_registry_url: Optional[str] = None  # Override global registry URL for this topic
    writer_schema_id: Optional[int] = None  # AVRO schema ID for producing messages
    correlation: Optional[CorrelationConfig] = None  # Correlation extraction/propagation rules


class TopicConfigLoader:
    """Loads and manages topic configurations from YAML files."""

    def __init__(
        self,
        config_dir: str = "/config",
        scan_interval: int = 30,
        global_schema_registry_url: Optional[str] = None
    ):
        """
        Initialize the topic config loader.

        Args:
            config_dir: Base config directory path
            scan_interval: How often to scan for config changes (seconds)
            global_schema_registry_url: Global Schema Registry URL (can be overridden per topic)
        """
        self.config_dir = Path(config_dir)
        self.topic_config_dir = self.config_dir / "topic-config"
        self.scan_interval = scan_interval
        self.global_schema_registry_url = global_schema_registry_url
        self.configs: Dict[str, TopicConfig] = {}
        self._lock = threading.Lock()
        self._running = False
        self._scan_thread: Optional[threading.Thread] = None
        self._file_hashes: Dict[Path, str] = {}

    def start(self) -> None:
        """Start background scanning thread."""
        if not self._running:
            self._running = True
            self._scan_thread = threading.Thread(
                target=self._scan_loop,
                daemon=True,
                name="topic-config-scanner"
            )
            self._scan_thread.start()
            logger.info(f"Topic config scanner started (scan interval: {self.scan_interval}s)")

    def stop(self) -> None:
        """Stop background scanning thread."""
        self._running = False
        if self._scan_thread:
            self._scan_thread.join(timeout=5)

    def _scan_loop(self) -> None:
        """Background loop that periodically scans for config changes."""
        import time
        while self._running:
            try:
                self._load_configs()
            except Exception as e:
                logger.error(f"Error loading topic configs: {e}")
            time.sleep(self.scan_interval)

    def _load_configs(self) -> None:
        """Scan topic-config directory and load all YAML files (supporting multiple documents per file)."""
        if not self.topic_config_dir.exists():
            logger.debug(f"Topic config directory does not exist: {self.topic_config_dir}")
            return

        import hashlib
        new_configs = {}
        new_file_hashes = {}

        yaml_files = sorted(self.topic_config_dir.glob("**/*.yaml")) + \
                     sorted(self.topic_config_dir.glob("**/*.yml"))

        for yaml_file in yaml_files:
            try:
                # Check if file has changed
                with open(yaml_file, 'rb') as f:
                    content = f.read()
                    file_hash = hashlib.md5(content).hexdigest()
                    new_file_hashes[yaml_file] = file_hash

                if yaml_file in self._file_hashes and self._file_hashes[yaml_file] == file_hash:
                    # File hasn't changed
                    for config in self.configs.values():
                        if config.topic not in new_configs:
                            new_configs[config.topic] = config
                    continue

                # File is new or changed - load it (may return multiple configs)
                topic_configs = self._parse_topic_config_file(yaml_file)
                for topic_config in topic_configs:
                    new_configs[topic_config.topic] = topic_config
                    logger.debug(f"Loaded topic config: {topic_config.topic} from {yaml_file}")

            except Exception as e:
                logger.error(f"Failed to load topic config from {yaml_file}: {e}")

        with self._lock:
            self.configs = new_configs
            self._file_hashes = new_file_hashes

    def _parse_topic_config_file(self, yaml_file: Path) -> List[TopicConfig]:
        """Parse a single topic config YAML file (may contain multiple documents)."""
        with open(yaml_file, 'r') as f:
            # Use safe_load_all to support multiple documents in one file (separated by ---)
            documents = list(yaml.safe_load_all(f))

        if not documents:
            raise ValueError(f"Topic config file is empty: {yaml_file}")

        # Filter out None values (empty documents)
        documents = [doc for doc in documents if doc is not None]

        if not documents:
            raise ValueError(f"Topic config file contains no valid documents: {yaml_file}")

        configs = []
        for doc_idx, data in enumerate(documents):
            if not isinstance(data, dict):
                raise ValueError(f"Document {doc_idx} in {yaml_file} must be a dictionary, got {type(data)}")

            if "topic" not in data:
                raise ValueError(f"Document {doc_idx} in {yaml_file}: Missing required field 'topic'")

            topic_name = data["topic"]
            message_format = data.get("message", {}).get("format", "json")
            schema_registry_url = data.get("message", {}).get("schema_registry_url")
            writer_schema_id = data.get("message", {}).get("writer_schema_id")

            # Use topic-specific registry URL if provided, else fall back to global
            if not schema_registry_url:
                schema_registry_url = self.global_schema_registry_url

            # Parse correlation config
            correlation_config = None
            if "correlation" in data:
                correlation_config = self._parse_correlation_config(data["correlation"])

            config = TopicConfig(
                topic=topic_name,
                message_format=message_format,
                schema_registry_url=schema_registry_url,
                writer_schema_id=writer_schema_id,
                correlation=correlation_config
            )
            configs.append(config)

        return configs

    def _parse_correlation_config(self, corr_data: Dict[str, Any]) -> CorrelationConfig:
        """Parse correlation configuration block."""
        extract_rules = []
        if "extract" in corr_data:
            for idx, rule_data in enumerate(corr_data["extract"]):
                rule = CorrelationExtractRule(
                    from_type=rule_data.get("from"),
                    name=rule_data.get("name"),
                    expression=rule_data.get("expression"),
                    priority=rule_data.get("priority", idx)  # Default to order in list
                )
                extract_rules.append(rule)

        # Sort by priority
        extract_rules.sort(key=lambda r: r.priority)

        propagate_rules = None
        if "propagate" in corr_data:
            propagate_rules = CorrelationPropagateRule(
                to_headers=corr_data["propagate"].get("to_headers")
            )

        return CorrelationConfig(extract=extract_rules, propagate=propagate_rules)

    def get_topic_config(self, topic: str) -> Optional[TopicConfig]:
        """Get configuration for a specific topic."""
        with self._lock:
            return self.configs.get(topic)

    def get_all_configs(self) -> Dict[str, TopicConfig]:
        """Get all topic configurations."""
        with self._lock:
            return dict(self.configs)

    def topic_exists(self, topic: str) -> bool:
        """Check if a topic has configuration."""
        with self._lock:
            return topic in self.configs

