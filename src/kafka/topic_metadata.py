"""
Topic metadata manager for dynamic topic discovery and type tracking.
Scans configuration files to extract topic names and their message types (json/avro/bytes).
"""
import logging
import time
import threading
from typing import Dict, Set, Optional
from pathlib import Path
from dataclasses import dataclass
import yaml

logger = logging.getLogger(__name__)


@dataclass
class TopicInfo:
    """Information about a Kafka topic."""
    name: str
    message_type: str = "json"  # json, avro, or bytes
    schema_id: Optional[int] = None
    schema_registry_url: Optional[str] = None


class TopicMetadataManager:
    """
    Scans rule and test suite YAML files to extract topics and their metadata.
    Maintains topic existence cache with periodic verification.
    """

    def __init__(
        self,
        config_dir: str = "/config",
        test_suite_dir: str = "/testSuite",
        kafka_client=None,
        scan_interval: int = 30,
        topic_check_interval: int = 10
    ):
        """
        Initialize topic metadata manager.

        Args:
            config_dir: Path to rules configuration directory
            test_suite_dir: Path to test suite directory
            kafka_client: KafkaClientWrapper for topic existence verification
            scan_interval: How often to scan YAML files (seconds)
            topic_check_interval: How often to retry verifying non-existent topics (seconds)
        """
        self.config_dir = Path(config_dir)
        self.test_suite_dir = Path(test_suite_dir)
        self.kafka_client = kafka_client
        self.scan_interval = scan_interval
        self.topic_check_interval = topic_check_interval

        self.topics: Dict[str, TopicInfo] = {}
        self.topic_existence: Dict[str, bool] = {}  # topic_name -> exists or not
        self.topic_last_check: Dict[str, float] = {}  # topic_name -> last check time

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
                name="topic-metadata-scanner"
            )
            self._scan_thread.start()
            # Do initial scan
            self._scan_all_files()
            logger.info("Topic metadata manager started")

    def stop(self) -> None:
        """Stop background scanning thread."""
        self._running = False
        if self._scan_thread:
            self._scan_thread.join(timeout=5)
            logger.info("Topic metadata manager stopped")

    def _scan_loop(self) -> None:
        """Background scanning loop."""
        while self._running:
            try:
                time.sleep(self.scan_interval)
                self._scan_all_files()
            except Exception as e:
                logger.error(f"Error in topic metadata scan loop: {e}")

    def _scan_all_files(self) -> None:
        """Scan all YAML files and extract topic metadata."""
        try:
            new_topics = {}

            # Scan rule files
            if self.config_dir.exists():
                for yaml_file in self.config_dir.rglob("*.yaml"):
                    self._extract_topics_from_file(yaml_file, new_topics, is_rule=True)
                for yaml_file in self.config_dir.rglob("*.yml"):
                    self._extract_topics_from_file(yaml_file, new_topics, is_rule=True)

            # Scan test suite files
            if self.test_suite_dir.exists():
                for yaml_file in self.test_suite_dir.rglob("*.test.yaml"):
                    self._extract_topics_from_file(yaml_file, new_topics, is_rule=False)
                for yaml_file in self.test_suite_dir.rglob("*.test.yml"):
                    self._extract_topics_from_file(yaml_file, new_topics, is_rule=False)

            with self._lock:
                self.topics = new_topics

        except Exception as e:
            logger.error(f"Error scanning YAML files: {e}")

    def _extract_topics_from_file(self, file_path: Path, topics_dict: Dict[str, TopicInfo], is_rule: bool) -> None:
        """Extract topics from a single YAML file."""
        try:
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)

            if not data or not isinstance(data, dict):
                return

            if is_rule:
                # Extract from rule configuration
                self._extract_topics_from_rule(data, topics_dict)
            else:
                # Extract from test suite configuration
                self._extract_topics_from_test(data, topics_dict)

        except Exception as e:
            logger.debug(f"Error extracting topics from {file_path}: {e}")

    def _extract_topics_from_rule(self, rule_data: Dict, topics_dict: Dict[str, TopicInfo]) -> None:
        """Extract input and output topics from rule YAML."""
        try:
            # Get input topic from 'when' block
            when_block = rule_data.get('when', {})
            if isinstance(when_block, dict):
                input_topic = when_block.get('topic')
                if input_topic:
                    # Check if topic metadata is specified in when block
                    message_type = when_block.get('message_type', 'json')
                    schema_id = when_block.get('schema_id')
                    schema_registry_url = when_block.get('schema_registry_url')

                    if input_topic not in topics_dict:
                        topics_dict[input_topic] = TopicInfo(
                            name=input_topic,
                            message_type=message_type,
                            schema_id=schema_id,
                            schema_registry_url=schema_registry_url
                        )

            # Get output topics from 'then' block
            then_block = rule_data.get('then', [])
            if not isinstance(then_block, list):
                then_block = [then_block]

            for output_item in then_block:
                if isinstance(output_item, dict):
                    output_topic = output_item.get('topic')
                    if output_topic:
                        # Check for message type metadata in output
                        message_type = output_item.get('message_type', 'json')
                        schema_id = output_item.get('schema_id')
                        schema_registry_url = output_item.get('schema_registry_url')

                        if output_topic not in topics_dict:
                            topics_dict[output_topic] = TopicInfo(
                                name=output_topic,
                                message_type=message_type,
                                schema_id=schema_id,
                                schema_registry_url=schema_registry_url
                            )

        except Exception as e:
            logger.debug(f"Error extracting topics from rule: {e}")

    def _extract_topics_from_test(self, test_data: Dict, topics_dict: Dict[str, TopicInfo]) -> None:
        """Extract topics from test suite YAML."""
        try:
            # Extract injection topics
            when_block = test_data.get('when', {})
            if isinstance(when_block, dict):
                injections = when_block.get('inject', [])
                if not isinstance(injections, list):
                    injections = [injections]

                for injection in injections:
                    if isinstance(injection, dict):
                        topic = injection.get('topic')
                        if topic:
                            message_type = injection.get('message_type', 'json')
                            schema_id = injection.get('schema_id')
                            if topic not in topics_dict:
                                topics_dict[topic] = TopicInfo(
                                    name=topic,
                                    message_type=message_type,
                                    schema_id=schema_id
                                )

            # Extract expectation topics
            then_block = test_data.get('then', {})
            if isinstance(then_block, dict):
                expectations = then_block.get('expectations', [])
                if not isinstance(expectations, list):
                    expectations = [expectations]

                for expectation in expectations:
                    if isinstance(expectation, dict):
                        topic = expectation.get('topic')
                        if topic:
                            message_type = expectation.get('message_type', 'json')
                            if topic not in topics_dict:
                                topics_dict[topic] = TopicInfo(
                                    name=topic,
                                    message_type=message_type
                                )

        except Exception as e:
            logger.debug(f"Error extracting topics from test: {e}")

    def get_all_topics(self) -> Set[str]:
        """Get all discovered topic names."""
        with self._lock:
            return set(self.topics.keys())

    def get_topic_info(self, topic: str) -> Optional[TopicInfo]:
        """Get metadata for a specific topic."""
        with self._lock:
            return self.topics.get(topic)

    def get_topic_type(self, topic: str) -> str:
        """
        Get message type for a topic (json, avro, or bytes).
        Defaults to 'json' if not specified.
        """
        with self._lock:
            info = self.topics.get(topic)
            return info.message_type if info else "json"

    def check_topic_exists(self, topic: str) -> bool:
        """
        Check if a topic exists, with periodic verification.
        Uses fixed interval retries for non-existent topics.
        """
        if not self.kafka_client:
            logger.warning("Kafka client not available for topic verification")
            return False

        current_time = time.time()

        with self._lock:
            # If recently checked and marked as not existing, respect retry interval
            if topic in self.topic_last_check:
                last_check = self.topic_last_check[topic]
                if not self.topic_existence.get(topic, False):
                    # Topic was marked as not existing
                    if current_time - last_check < self.topic_check_interval:
                        # Within retry interval, skip check
                        return False

        # Perform actual existence check
        try:
            exists = self.kafka_client._verify_topic_exists(topic)

            with self._lock:
                self.topic_existence[topic] = exists
                self.topic_last_check[topic] = current_time

            return exists
        except Exception as e:
            logger.debug(f"Error checking topic existence for '{topic}': {e}")
            return False

    def get_existing_topics(self) -> Set[str]:
        """Get all topics that are confirmed to exist in Kafka."""
        existing = set()
        for topic in self.get_all_topics():
            if self.check_topic_exists(topic):
                existing.add(topic)
        return existing

    def get_metadata_summary(self) -> Dict[str, any]:
        """Get summary of all topic metadata."""
        with self._lock:
            return {
                "total_topics": len(self.topics),
                "topics": {
                    name: {
                        "message_type": info.message_type,
                        "schema_id": info.schema_id,
                        "exists": self.topic_existence.get(name, "unknown")
                    }
                    for name, info in self.topics.items()
                }
            }

