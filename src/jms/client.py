"""
IBM MQ client wrapper for JMS message handling.
Supports put and get operations on queues/topics.
"""
import json
import logging
import threading
import time
import uuid
from typing import Dict, Any, List, Optional, Union

try:
    import ibm_mq as MQ
    from ibm_mq import MQException
    IBM_MQ_AVAILABLE = True
except ImportError:
    IBM_MQ_AVAILABLE = False
    MQException = Exception

from ..messaging import MessageClient

logger = logging.getLogger(__name__)


def get_ibm_mq_config(
    broker_url: str = "localhost(1414)",
    channel: str = "DEV.APP.SVRCONN",
    username: str = "",
    password: str = "",
    queue_manager: str = "QM1",
    ssl_key_store: Optional[str] = None,
    ssl_key_store_password: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build IBM MQ client configuration from environment variables or parameters.

    Environment variables:
    - IBM_MQ_BROKER_URL: Broker address (default: localhost(1414))
    - IBM_MQ_CHANNEL: Channel name (default: DEV.APP.SVRCONN)
    - IBM_MQ_QUEUE_MANAGER: Queue manager name (default: QM1)
    - IBM_MQ_USERNAME: Username for authentication
    - IBM_MQ_PASSWORD: Password for authentication
    - IBM_MQ_SSL_KEY_STORE: Path to SSL keystore file (PEM)
    - IBM_MQ_SSL_KEY_STORE_PASSWORD: Password for SSL keystore

    Args:
        broker_url: Broker connection string
        channel: Channel name
        username: Username
        password: Password
        queue_manager: Queue manager name
        ssl_key_store: SSL keystore path
        ssl_key_store_password: SSL keystore password

    Returns:
        Configuration dictionary
    """
    import os

    config = {
        "broker_url": os.getenv("IBM_MQ_BROKER_URL", broker_url),
        "channel": os.getenv("IBM_MQ_CHANNEL", channel),
        "queue_manager": os.getenv("IBM_MQ_QUEUE_MANAGER", queue_manager),
        "username": os.getenv("IBM_MQ_USERNAME", username),
        "password": os.getenv("IBM_MQ_PASSWORD", password),
        "ssl_key_store": os.getenv("IBM_MQ_SSL_KEY_STORE", ssl_key_store),
        "ssl_key_store_password": os.getenv(
            "IBM_MQ_SSL_KEY_STORE_PASSWORD", ssl_key_store_password
        ),
    }

    logger.info(
        f"IBM MQ Config: QM={config['queue_manager']}, "
        f"Channel={config['channel']}, Broker={config['broker_url']}"
    )

    return config


class IBMMQClientWrapper(MessageClient):
    """
    IBM MQ client wrapper implementing MessageClient interface.
    Supports connecting to IBM Message Queue systems.
    """

    def __init__(
        self,
        broker_url: str = "localhost(1414)",
        channel: str = "DEV.APP.SVRCONN",
        username: str = "",
        password: str = "",
        queue_manager: str = "QM1",
        ssl_key_store: Optional[str] = None,
        ssl_key_store_password: Optional[str] = None,
    ):
        """
        Initialize IBM MQ client.

        Args:
            broker_url: Broker connection string
            channel: Channel name
            username: Username
            password: Password
            queue_manager: Queue manager name
            ssl_key_store: SSL keystore path
            ssl_key_store_password: SSL keystore password
        """
        if not IBM_MQ_AVAILABLE:
            raise ImportError("IBM MQ library (ibm-mq) is not installed. Install from IBM's repository: pip install ibm-mq --index-url https://public.dhe.ibm.com/ibmdl/export/pub/software/websphere/messaging/mqpython/")

        self.config = get_ibm_mq_config(
            broker_url=broker_url,
            channel=channel,
            username=username,
            password=password,
            queue_manager=queue_manager,
            ssl_key_store=ssl_key_store,
            ssl_key_store_password=ssl_key_store_password,
        )

        self.broker_url = broker_url
        self.channel = channel
        self.queue_manager = queue_manager
        self.username = username
        self.password = password

        self.qmgr = None
        self.hconn = None
        self._lock = threading.Lock()
        self._connect()

    def _connect(self) -> None:
        """Connect to IBM MQ queue manager."""
        max_retries = 5
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                # Build connection name
                conn_name = self.config["broker_url"]

                # Prepare connection options
                connect_options = MQ.CMQC.MQCO_NONE
                if self.config["ssl_key_store"]:
                    connect_options |= MQ.CMQC.MQCO_TLS_REQUIRED

                # Connect to queue manager
                self.hconn = MQ.MQConnX(
                    self.queue_manager,
                    user=self.username,
                    password=self.password,
                )

                logger.info(f"Connected to IBM MQ: {self.queue_manager}")
                return

            except MQException as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"MQ connection attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error(
                        f"Failed to connect to IBM MQ after {max_retries} attempts: {e}"
                    )
                    raise
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Unexpected error connecting to MQ (attempt {attempt + 1}): {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Failed to connect to IBM MQ: {e}")
                    raise

    def produce(
        self,
        destination: str,
        message: Union[str, Dict[str, Any], bytes],
        headers: Optional[Dict[str, str]] = None,
        key: Optional[str] = None,
        schema_id: Optional[int] = None,
    ) -> Optional[str]:
        """
        Put a message to a JMS queue.

        Args:
            destination: Queue name
            message: Message payload (dict, string, or bytes)
            headers: Optional message properties
            key: Ignored for JMS (included for interface compatibility)
            schema_id: Ignored for JMS (included for interface compatibility)

        Returns:
            Message ID or None if failed
        """
        try:
            if not self.hconn:
                logger.error("IBM MQ connection not established")
                return None

            # Serialize message
            if isinstance(message, dict):
                message_bytes = json.dumps(message).encode("utf-8")
            elif isinstance(message, bytes):
                message_bytes = message
            else:
                message_bytes = str(message).encode("utf-8")

            # Open queue for output
            queue_options = MQ.CMQC.MQOO_OUTPUT | MQ.CMQC.MQOO_FAIL_IF_QUIESCING
            hqueue = MQ.MQOpen(self.hconn, destination, queue_options)

            # Prepare message descriptor
            md = MQ.md()

            # Add custom properties to message descriptor
            if headers:
                # Store headers in message properties (MQ format)
                hmsg = MQ.MQCreateMessage(self.hconn, md, message_bytes)
                for key, value in headers.items():
                    try:
                        MQ.MQSetProperty(
                            hmsg,
                            MQ.CMQC.MQPROP_PUT_APPL_TYPE,
                            MQ.CMQC.MQAT_APPLTYPE_MSGCLIENT,
                        )
                    except Exception as e:
                        logger.debug(f"Could not set property {key}: {e}")
            else:
                hmsg = None

            # Put message
            if hmsg:
                MQ.MQPut(self.hconn, hqueue, md, message_bytes, hmsg)
            else:
                MQ.MQPut(self.hconn, hqueue, md, message_bytes)

            # Generate message ID
            message_id = str(uuid.uuid4())

            logger.debug(f"Message {message_id} sent to queue {destination}")

            # Close queue
            MQ.MQClose(hqueue)

            return message_id

        except MQException as e:
            logger.error(f"Error producing message to {destination}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error producing message to {destination}: {e}")
            return None

    def consume(
        self, destination: str, limit: int = 10, timeout_ms: int = 5000
    ) -> List[Dict[str, Any]]:
        """
        Get messages from a JMS queue.

        Args:
            destination: Queue name
            limit: Maximum number of messages to retrieve
            timeout_ms: Timeout in milliseconds per message

        Returns:
            List of message dictionaries
        """
        messages = []

        try:
            if not self.hconn:
                logger.error("IBM MQ connection not established")
                return messages

            # Open queue for input
            queue_options = (
                MQ.CMQC.MQOO_INPUT_AS_Q_DEF | MQ.CMQC.MQOO_FAIL_IF_QUIESCING
            )
            hqueue = MQ.MQOpen(self.hconn, destination, queue_options)

            # Get messages
            md = MQ.md()
            gmo = MQ.gmo()
            gmo.Options = MQ.CMQC.MQGMO_NO_SYNCPOINT
            gmo.WaitInterval = timeout_ms

            message_count = 0
            while message_count < limit:
                try:
                    msg = MQ.MQGet(self.hconn, hqueue, md, gmo)

                    if not msg:
                        break

                    # Parse message
                    try:
                        decoded_msg = json.loads(msg.decode("utf-8"))
                        msg_format = "json"
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        decoded_msg = msg
                        msg_format = "bytes"

                    messages.append(
                        {
                            "value": decoded_msg,
                            "format": msg_format,
                            "timestamp": int(time.time() * 1000),
                            "offset": message_count,
                            "partition": 0,
                            "key": None,
                            "headers": {},
                        }
                    )

                    message_count += 1

                except MQException as e:
                    if e.reason == MQ.CMQC.MQRC_NO_MSG_AVAILABLE:
                        break  # No more messages
                    else:
                        logger.warning(f"Error getting message from queue: {e}")
                        break

            # Close queue
            MQ.MQClose(hqueue)

            logger.debug(f"Retrieved {len(messages)} messages from queue {destination}")

            return messages

        except MQException as e:
            logger.error(f"Error consuming from queue {destination}: {e}")
            return messages
        except Exception as e:
            logger.error(
                f"Unexpected error consuming from queue {destination}: {e}"
            )
            return messages

    def close(self) -> None:
        """Close connection to IBM MQ."""
        try:
            if self.hconn:
                MQ.MQDisconn(self.hconn)
                logger.info("Disconnected from IBM MQ")
        except Exception as e:
            logger.error(f"Error closing IBM MQ connection: {e}")

