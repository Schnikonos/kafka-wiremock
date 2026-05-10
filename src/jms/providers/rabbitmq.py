"""
RabbitMQ provider implementation using AMQP protocol via pika.
"""
import json
import logging
import uuid
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

try:
    import pika
    PIKA_AVAILABLE = True
except ImportError:
    PIKA_AVAILABLE = False

from .base import JMSProvider, JMSMessage

logger = logging.getLogger(__name__)


class RabbitMQProvider(JMSProvider):
    """RabbitMQ provider using AMQP protocol via pika library."""

    def __init__(
        self,
        broker_url: str = "localhost:5672",
        username: str = "guest",
        password: str = "guest",
        virtual_host: str = "/",
        **kwargs  # Ignore extra provider-specific config
    ):
        """
        Initialize RabbitMQ provider.

        Args:
            broker_url: Broker URL (e.g., 'localhost:5672' or 'rabbitmq.example.com:5672')
            username: Username for authentication (default: guest)
            password: Password for authentication (default: guest)
            virtual_host: RabbitMQ virtual host (default: /)
        """
        if not PIKA_AVAILABLE:
            raise ImportError(
                "RabbitMQ provider requires pika. Install with: pip install pika==1.3.0"
            )

        self.broker_url = broker_url
        self.username = username
        self.password = password
        self.virtual_host = virtual_host

        # Parse broker URL
        parsed = urlparse(f"//{broker_url}")
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or 5672

        self.connection = None
        self.channel = None
        self._connected = False

        # Auto-connect on initialization
        try:
            self.connect()
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

    def connect(self) -> None:
        """Establish connection to RabbitMQ broker."""
        if self._connected and self.connection and self.channel:
            logger.debug("Already connected to RabbitMQ")
            return

        try:
            # Create credentials
            credentials = pika.PlainCredentials(self.username, self.password)

            # Create connection parameters
            parameters = pika.ConnectionParameters(
                host=self.host,
                port=self.port,
                virtual_host=self.virtual_host,
                credentials=credentials,
                connection_attempts=5,
                retry_delay=2,
                socket_connect_timeout=10
            )

            # Connect
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()

            self._connected = True
            logger.info(f"Connected to RabbitMQ at {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            self._connected = False
            raise ConnectionError(f"Failed to connect to RabbitMQ: {e}")

    def disconnect(self) -> None:
        """Close connection to RabbitMQ broker."""
        try:
            if self.channel:
                self.channel.close()
            if self.connection:
                self.connection.close()
            logger.info("Disconnected from RabbitMQ")
        except Exception as e:
            logger.warning(f"Error disconnecting from RabbitMQ: {e}")
        finally:
            self.connection = None
            self.channel = None
            self._connected = False

    def is_connected(self) -> bool:
        """Check if connection is active."""
        if not (self._connected and self.connection and self.channel):
            return False
        try:
            return self.connection.is_open and self.channel.is_open
        except Exception:
            return False

    def put_message(
        self,
        destination: str,
        payload: str,
        headers: Optional[Dict[str, str]] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Send a message to a RabbitMQ queue/exchange.

        Args:
            destination: Queue or exchange name
            payload: Message payload (JSON or string)
            headers: Optional message headers (converted to AMQP headers)
            properties: Optional AMQP properties

        Returns:
            Message ID of sent message
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to RabbitMQ")

        try:
            # Declare queue to ensure it exists
            self.channel.queue_declare(
                queue=destination,
                durable=True,
                auto_delete=False,
                exclusive=False
            )

            # Prepare message ID
            msg_id = str(uuid.uuid4())

            # Prepare basic properties
            amqp_headers = dict(headers) if headers else {}
            amqp_properties = pika.BasicProperties(
                content_type="application/json",
                content_encoding="utf-8",
                headers=amqp_headers,
                delivery_mode=2,  # Persistent
                message_id=msg_id,
                timestamp=int(__import__('time').time() * 1000)
            )

            # Publish message
            self.channel.basic_publish(
                exchange="",
                routing_key=destination,
                body=payload.encode('utf-8') if isinstance(payload, str) else payload,
                properties=amqp_properties
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
        Retrieve messages from a RabbitMQ queue.

        Args:
            destination: Queue name
            timeout_ms: Timeout in milliseconds (note: RabbitMQ blocks until message)
            max_messages: Maximum number of messages to retrieve

        Returns:
            List of JMSMessage objects
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to RabbitMQ")

        messages = []

        try:
            # Declare queue to ensure it exists
            self.channel.queue_declare(
                queue=destination,
                durable=True,
                auto_delete=False,
                exclusive=False
            )

            # Get messages (non-blocking with timeout)
            for _ in range(max_messages):
                method, properties, body = self.channel.basic_get(
                    queue=destination,
                    auto_ack=True
                )

                if body:
                    try:
                        payload = body.decode('utf-8')
                    except UnicodeDecodeError:
                        payload = body.hex()

                    msg_properties = {}
                    if properties.headers:
                        msg_properties.update(properties.headers)
                    if properties.message_id:
                        msg_properties['message_id'] = properties.message_id

                    message = JMSMessage(
                        destination=destination,
                        payload=payload,
                        properties=msg_properties
                    )
                    messages.append(message)
                else:
                    # No message available
                    break

        except Exception as e:
            logger.warning(f"Failed to get message from {destination}: {e}")

        return messages

    def validate_connection(self) -> bool:
        """Test if connection is valid and responsive."""
        if not self.is_connected():
            return False

        try:
            # Try to declare a test queue and then delete it
            test_queue = f"__test_{uuid.uuid4().hex[:8]}"
            self.channel.queue_declare(
                queue=test_queue,
                durable=False,
                auto_delete=True,
                exclusive=False
            )
            self.channel.queue_delete(queue=test_queue, if_empty=False)
            return True
        except Exception as e:
            logger.debug(f"Connection validation failed: {e}")
            return False

    def get_destination_stats(self, destination: str) -> Dict[str, Any]:
        """Get statistics for a queue."""
        if not self.is_connected():
            return {"error": "Not connected"}

        try:
            # Declare queue passively to check existence and get message count
            method = self.channel.queue_declare(
                queue=destination,
                durable=True,
                auto_delete=False,
                exclusive=False,
                passive=True
            )

            return {
                "name": destination,
                "message_count": method.method.message_count,
                "consumer_count": method.method.consumer_count
            }
        except Exception as e:
            logger.debug(f"Failed to get stats for {destination}: {e}")
            return {"name": destination, "error": str(e)}

    def list_destinations(self) -> List[str]:
        """List all available queues on the broker."""
        if not self.is_connected():
            return []

        # RabbitMQ AMQP doesn't provide queue enumeration via pika
        # This would require using the Management API separately
        logger.debug("Queue enumeration requires RabbitMQ Management API")
        return []

    def close(self) -> None:
        """Close connection and cleanup resources."""
        self.disconnect()

