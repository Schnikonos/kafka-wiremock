"""
Message cache for test suite - stores messages received from Kafka topics
with TTL so tests can query them instead of polling Kafka directly.
"""
import logging
import time
import threading
from typing import Dict, List, Optional, Any
from threading import Lock
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CachedMessage:
    """A message stored in the cache with timestamp."""
    value: Any
    timestamp: int
    partition: int
    offset: int
    headers: Optional[Dict[str, str]]
    cached_at: float  # When it was added to cache


class MessageCache:
    """
    In-memory cache for Kafka messages consumed by TEST listeners only.
    Tests query this cache instead of polling Kafka directly.

    Features:
    - Automatic TTL expiration (default 2 minutes)
    - Per-topic message queues
    - Thread-safe
    - Efficient lookup for test assertions
    - Background cleanup thread to prevent memory leaks

    Note: This cache is ONLY for test listeners, NOT for rule listeners.
    Rule listeners still apply rules directly without caching.
    """

    def __init__(self, ttl_seconds: int = 120, cleanup_interval_seconds: int = 30):
        """
        Initialize message cache with background cleanup.

        Args:
            ttl_seconds: Time-to-live for messages in cache (default 2 minutes)
            cleanup_interval_seconds: How often to run cleanup (default 30 seconds)
        """
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.messages: Dict[str, List[CachedMessage]] = defaultdict(list)
        self._lock = Lock()
        self._running = False
        self._cleanup_thread: Optional[threading.Thread] = None

    def start_cleanup(self) -> None:
        """Start background cleanup thread."""
        if not self._running:
            self._running = True
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                daemon=True,
                name="message-cache-cleanup"
            )
            self._cleanup_thread.start()
            logger.info(f"Message cache cleanup started (interval: {self.cleanup_interval_seconds}s)")

    def stop_cleanup(self) -> None:
        """Stop background cleanup thread."""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
            logger.info("Message cache cleanup stopped")

    def _cleanup_loop(self) -> None:
        """Background cleanup loop that runs periodically."""
        while self._running:
            try:
                time.sleep(self.cleanup_interval_seconds)
                if not self._running:
                    break
                self._cleanup_all_expired()
            except Exception as e:
                logger.error(f"Error in cache cleanup loop: {e}")

    def add_message(
        self,
        topic: str,
        value: Any,
        timestamp: int = 0,
        partition: int = 0,
        offset: int = 0,
        headers: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Add a message to the cache.

        Args:
            topic: Kafka topic
            value: Message value
            timestamp: Message timestamp
            partition: Kafka partition
            offset: Kafka offset
            headers: Message headers
        """
        with self._lock:
            msg = CachedMessage(
                value=value,
                timestamp=timestamp,
                partition=partition,
                offset=offset,
                headers=headers,
                cached_at=time.time()
            )
            self.messages[topic].append(msg)
            self._cleanup_expired(topic)

    def get_messages(self, topic: str, since: Optional[float] = None) -> List[CachedMessage]:
        """
        Get all non-expired messages from a topic.

        Args:
            topic: Kafka topic
            since: Only return messages cached after this timestamp (optional)

        Returns:
            List of cached messages
        """
        with self._lock:
            self._cleanup_expired(topic)
            messages = self.messages.get(topic, [])

            if since is not None:
                messages = [m for m in messages if m.cached_at >= since]

            return messages

    def clear_topic(self, topic: str) -> None:
        """Clear all messages for a topic."""
        with self._lock:
            if topic in self.messages:
                del self.messages[topic]

    def clear_all(self) -> None:
        """Clear all cached messages."""
        with self._lock:
            self.messages.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            stats = {
                "topics": len(self.messages),
                "total_messages": sum(len(msgs) for msgs in self.messages.values()),
                "by_topic": {
                    topic: len(msgs)
                    for topic, msgs in self.messages.items()
                }
            }
            return stats

    def _cleanup_expired(self, topic: str) -> None:
        """Remove expired messages from a topic (call with lock held)."""
        if topic not in self.messages:
            return

        current_time = time.time()
        before_count = len(self.messages[topic])
        self.messages[topic] = [
            msg for msg in self.messages[topic]
            if (current_time - msg.cached_at) < self.ttl_seconds
        ]
        after_count = len(self.messages[topic])

        if before_count > after_count:
            logger.debug(f"Cache cleanup for topic '{topic}': removed {before_count - after_count} expired messages")

    def _cleanup_all_expired(self) -> None:
        """Remove all expired messages from all topics (background cleanup)."""
        with self._lock:
            current_time = time.time()
            total_removed = 0

            for topic in list(self.messages.keys()):
                before_count = len(self.messages[topic])
                self.messages[topic] = [
                    msg for msg in self.messages[topic]
                    if (current_time - msg.cached_at) < self.ttl_seconds
                ]
                after_count = len(self.messages[topic])
                removed = before_count - after_count
                total_removed += removed

                # Remove topic key if empty
                if not self.messages[topic]:
                    del self.messages[topic]

            if total_removed > 0:
                logger.debug(f"Message cache cleanup: removed {total_removed} expired messages across all topics")




