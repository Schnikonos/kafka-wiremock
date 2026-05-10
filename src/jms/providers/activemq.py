"""
ActiveMQ provider implementation using STOMP protocol.
"""
import json
import logging
import uuid
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

try:
    import stomp
    STOMP_AVAILABLE = True
except ImportError:
    STOMP_AVAILABLE = False

from .base import JMSProvider, JMSMessage

logger = logging.getLogger(__name__)


class ActiveMQProvider(JMSProvider):
    """ActiveMQ provider using STOMP protocol."""

    def __init__(
        self,
        broker_url: str = "localhost:61613",
        username: str = "",
        password: str = "",
        vhost: str = None,
        **kwargs  # Ignore extra provider-specific config
    ):
        """
        Initialize ActiveMQ provider.

        Args:
            broker_url: Broker URL (e.g., 'localhost:61613' or 'activemq.example.com:61613')
            username: Username for authentication
            password: Password for authentication
            vhost: Virtual host (optional, rarely used with ActiveMQ)
        """
        if not STOMP_AVAILABLE:
            raise ImportError(
                "ActiveMQ provider requires stomp.py. Install with: pip install stomp.py==8.1.0"
            )

        self.broker_url = broker_url
        self.username = username
        self.password = password
        self.vhost = vhost or "/"

        # Parse broker URL
        parsed = urlparse(f"//{broker_url}")
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or 61613

        self.connection = None
        self._connected = False
        self._message_queue = []

        # Auto-connect on initialization
        try:
            self.connect()
        except Exception as e:
            logger.error(f"Failed to connect to ActiveMQ: {e}")
            raise

    def connect(self) -> None:
        """Establish connection to ActiveMQ broker."""
        if self._connected and self.connection:
            logger.debug("Already connected to ActiveMQ")
            return

        try:
            # Create STOMP connection
            self.connection = stomp.Connection(
                [(self.host, self.port)],
                auto_content_length=False
            )

            # Set headers for connection
            headers = {}
            if self.username:
                headers = {
                    "login": self.username,
                    "passcode": self.password,
                    "host": self.vhost
                }

            # Add listener for incoming messages
            self.connection.set_listener('', MessageListener(self._message_queue))

            # Connect
            self.connection.connect(**headers, wait=True)
            self._connected = True
            logger.info(f"Connected to ActiveMQ at {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to ActiveMQ: {e}")
            self._connected = False
            raise ConnectionError(f"Failed to connect to ActiveMQ: {e}")

    def disconnect(self) -> None:
        """Close connection to ActiveMQ broker."""
        if self.connection:
            try:
                self.connection.disconnect()
                logger.info("Disconnected from ActiveMQ")
            except Exception as e:
                logger.warning(f"Error disconnecting from ActiveMQ: {e}")
            finally:
                self.connection = None
                self._connected = False

    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self._connected and self.connection is not None and self.connection.is_connected()

    def put_message(
        self,
        destination: str,
        payload: str,
        headers: Optional[Dict[str, str]] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Send a message to an ActiveMQ queue/topic.

        Args:
            destination: Queue or topic name
            payload: Message payload (JSON or string)
            headers: Optional message headers
            properties: Optional STOMP headers

        Returns:
            Message ID of sent message
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to ActiveMQ")

        try:
            # Prepare headers
            msg_headers = {}
            if properties:
                msg_headers.update(properties)
            if headers:
                msg_headers.update(headers)

            # Generate message ID
            msg_id = str(uuid.uuid4())
            msg_headers["message-id"] = msg_id

            # Send message
            self.connection.send(
                body=payload,
                destination=destination,
                headers=msg_headers
            )

            logger.debug(f"Sent message to {destination}: {msg_id}")
            return msg_id
        except Exception as e:
            logger.error(f"Failed to send message to {destination}: {e}")
            raise

    def get_message(
        self,
        destination: str,
        timeout_ms: int = 1000,
        max_messages: int = 1,
    ) -> List[JMSMessage]:
        """
        Retrieve messages from an ActiveMQ queue.

        Args:
            destination: Queue name (not topic)
            timeout_ms: Timeout in milliseconds
            max_messages: Maximum number of messages to retrieve

        Returns:
            List of JMSMessage objects
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to ActiveMQ")

        messages = []

        try:
            # Subscribe to queue
            sub_id = f"sub-{uuid.uuid4().hex[:8]}"
            self.connection.subscribe(
                destination=destination,
                id=sub_id,
                ack="auto"
            )

            # Wait for messages with timeout
            import time
            start_time = time.time()
            timeout_sec = timeout_ms / 1000.0

            while len(messages) < max_messages:
                if time.time() - start_time > timeout_sec:
                    break

                # Check message queue
                if self._message_queue:
                    frame = self._message_queue.pop(0)
                    messages.append(
                        JMSMessage(
                            destination=destination,
                            payload=frame.body if frame.body else "",
                            properties=dict(frame.headers) if frame.headers else {}
                        )
                    )
                else:
                    time.sleep(0.01)  # Small sleep to avoid busy-wait

            # Unsubscribe
            self.connection.unsubscribe(id=sub_id)

        except Exception as e:
            logger.warning(f"Failed to get message from {destination}: {e}")

        return messages

    def validate_connection(self) -> bool:
        """Test if connection is valid and responsive."""
        if not self.is_connected():
            return False

        try:
            # STOMP doesn't have a built-in heartbeat check,
            # so we rely on the is_connected() check
            return self.connection.is_connected()
        except Exception as e:
            logger.debug(f"Connection validation failed: {e}")
            return False

    def get_destination_stats(self, destination: str) -> Dict[str, Any]:
        """Get statistics for a queue."""
        if not self.is_connected():
            return {"error": "Not connected"}

        # ActiveMQ STOMP protocol doesn't provide direct queue stats access
        # This would require using the management interface separately
        return {
            "name": destination,
            "note": "Queue stats require ActiveMQ management interface"
        }

    def list_destinations(self) -> List[str]:
        """List all available queues on the broker."""
        if not self.is_connected():
            return []

        # ActiveMQ STOMP protocol doesn't provide queue enumeration via STOMP
        # This would require using the management interface separately
        logger.debug("Queue enumeration not available via STOMP protocol")
        return []

    def close(self) -> None:
        """Close connection and cleanup resources."""
        self.disconnect()


class MessageListener(stomp.ConnectionListener):
    """STOMP message listener for capturing incoming messages."""

    def __init__(self, message_queue: List):
        """
        Initialize listener.

        Args:
            message_queue: List to append received frames to
        """
        self.message_queue = message_queue

    def on_connecting(self, headers, body):
        """Called when connection is being established."""
        pass

    def on_connected(self, headers, body):
        """Called when connection is established."""
        logger.debug("STOMP connection established")

    def on_disconnected(self):
        """Called when connection is closed."""
        logger.debug("STOMP connection disconnected")

    def on_message(self, frame):
        """Called when message is received."""
        self.message_queue.append(frame)

    def on_error(self, headers, body):
        """Called when error frame is received."""
        logger.error(f"STOMP error: {body}")

    def on_receipt(self, headers, body):
        """Called when receipt frame is received."""
        pass

