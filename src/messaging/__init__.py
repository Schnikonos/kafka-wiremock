"""Messaging abstraction layer supporting Kafka and JMS."""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union, Tuple

__all__ = ["MessageClient", "MessageListener"]


class MessageClient(ABC):
    """Abstract base class for message producers/consumers."""

    @abstractmethod
    def produce(
        self,
        destination: str,
        message: Union[str, Dict[str, Any], bytes],
        headers: Optional[Dict[str, str]] = None,
        key: Optional[str] = None,
        schema_id: Optional[int] = None,
    ) -> Optional[str]:
        """
        Produce a message to destination (topic/queue).

        Args:
            destination: Topic name (Kafka) or Queue name (JMS)
            message: Message payload
            headers: Optional message headers/properties
            key: Optional message key (Kafka only)
            schema_id: Optional AVRO schema ID

        Returns:
            Message ID or None if failed
        """
        pass

    @abstractmethod
    def consume(
        self, destination: str, limit: int = 10, timeout_ms: int = 5000
    ) -> List[Dict[str, Any]]:
        """
        Consume messages from destination.

        Args:
            destination: Topic name (Kafka) or Queue name (JMS)
            limit: Maximum number of messages to consume
            timeout_ms: Timeout in milliseconds

        Returns:
            List of message dictionaries
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the client and release resources."""
        pass


class MessageListener(ABC):
    """Abstract base class for message listeners (subscribers)."""

    @abstractmethod
    def start(self) -> None:
        """Start listening to messages."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop listening to messages."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Check if listener is running."""
        pass

