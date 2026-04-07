"""
Test Listener Manager - Scans test files and ensures listeners are started for test expectation topics.
Similar to how rule listeners are started from config, but for test expectations.
"""
import logging
import threading
import time
from pathlib import Path
from typing import Set, Optional
from .loader import TestLoader

logger = logging.getLogger(__name__)


class TestListenerManager:
    """
    Periodically scans test files to discover expectation topics and ensures
    listeners are started for them. This makes test startup faster by pre-starting
    listeners instead of waiting for them on-demand.
    """

    def __init__(self, listener_engine, test_loader: TestLoader, scan_interval: int = 30):
        """
        Initialize test listener manager.

        Args:
            listener_engine: KafkaListenerEngine instance to start listeners
            test_loader: TestLoader instance to discover tests
            scan_interval: How often to scan test files (default 30 seconds)
        """
        self.listener_engine = listener_engine
        self.test_loader = test_loader
        self.scan_interval = scan_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._known_topics: Set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the test listener manager."""
        if not self._running:
            self._running = True
            self._thread = threading.Thread(
                target=self._scan_loop,
                daemon=True,
                name="test-listener-manager"
            )
            self._thread.start()
            logger.info(f"Test listener manager started (scan interval: {self.scan_interval}s)")

    def stop(self) -> None:
        """Stop the test listener manager."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            logger.info("Test listener manager stopped")

    def _scan_loop(self) -> None:
        """Background loop that periodically scans test files."""
        while self._running:
            try:
                self._scan_test_files()
                time.sleep(self.scan_interval)
            except Exception as e:
                logger.error(f"Error in test listener manager scan loop: {e}")

    def _scan_test_files(self) -> None:
        """Scan test files and discover expectation topics."""
        try:
            # Load all tests
            tests = self.test_loader.discover_tests()

            # Extract all expectation topics
            expectation_topics = set()
            for test in tests:
                for item in test.then.items:
                    # Check if it's an expectation (has topic attribute)
                    if hasattr(item, 'topic'):
                        expectation_topics.add(item.topic)

            if not expectation_topics:
                return

            # Check which topics are new
            with self._lock:
                new_topics = expectation_topics - self._known_topics

            if not new_topics:
                return

            logger.info(f"Discovered {len(new_topics)} new test expectation topic(s): {new_topics}")

            # Ensure listeners are started for new topics (only if topic exists)
            for topic in new_topics:
                try:
                    # Check if topic exists in Kafka
                    if self.listener_engine.kafka_client._verify_topic_exists(topic):
                        logger.info(f"Starting listener for test expectation topic: {topic}")
                        if self.listener_engine.ensure_listening_to_topic(topic, timeout_seconds=2):
                            logger.info(f"Listener ready for test topic: {topic}")
                        else:
                            logger.warning(f"Failed to start listener for test topic: {topic}")
                    else:
                        logger.debug(f"Test expectation topic not yet available: {topic}")
                except Exception as e:
                    logger.error(f"Failed to start listener for topic {topic}: {e}")

            # Update known topics
            with self._lock:
                self._known_topics.update(new_topics)

        except Exception as e:
            logger.error(f"Error scanning test files: {e}")

