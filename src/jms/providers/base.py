"""
Abstract base class for JMS providers.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class JMSMessage:
    """Represents a JMS message."""
    destination: str
    payload: str
    headers: Optional[Dict[str, str]] = None
    properties: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None


class JMSProvider(ABC):
    """Abstract base class for JMS message brokers."""

    @abstractmethod
    def connect(self) -> None:
        """
        Establish connection to the message broker.

        Raises:
            ConnectionError: If connection fails
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """
        Close connection to the message broker gracefully.
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if connection is active.

        Returns:
            True if connected, False otherwise
        """
        pass

    @abstractmethod
    def put_message(
        self,
        destination: str,
        payload: str,
        headers: Optional[Dict[str, str]] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Send a message to a destination (queue or topic).

        Args:
            destination: Queue or topic name
            payload: Message payload (JSON or string)
            headers: Optional message headers
            properties: Optional JMS properties

        Returns:
            Message ID of sent message

        Raises:
            ConnectionError: If not connected
            ValueError: If destination or payload invalid
        """
        pass

    @abstractmethod
    def get_message(
        self,
        destination: str,
        timeout_ms: int = 1000,
        max_messages: int = 1,
    ) -> List[JMSMessage]:
        """
        Retrieve messages from a destination with timeout.

        Args:
            destination: Queue or topic name
            timeout_ms: Timeout in milliseconds
            max_messages: Maximum number of messages to retrieve

        Returns:
            List of JMSMessage objects (empty if timeout)

        Raises:
            ConnectionError: If not connected
            ValueError: If destination invalid
        """
        pass

    @abstractmethod
    def validate_connection(self) -> bool:
        """
        Test if connection is valid and responsive.

        Returns:
            True if connection is valid, False otherwise
        """
        pass

    @abstractmethod
    def get_destination_stats(self, destination: str) -> Dict[str, Any]:
        """
        Get statistics for a queue (message count, etc.).

        Args:
            destination: Queue or topic name

        Returns:
            Dictionary with stats (implementation-specific)
        """
        pass

    @abstractmethod
    def list_destinations(self) -> List[str]:
        """
        List all available queues/topics on the broker.

        Returns:
            List of destination names
        """
        pass

    def get_provider_type(self) -> str:
        """Get provider type identifier (e.g., 'ibm_mq', 'activemq', 'rabbitmq')."""
        class_name = self.__class__.__name__
        # Convert CamelCase to snake_case
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
        provider = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        # Remove trailing provider
        return provider.replace('_provider', '').lower()

