"""
IBM MQ provider implementation using pymqi.
pymqi is an open-source Python library available on PyPI for IBM MQ integration.
"""
import json
import logging
import threading
import time
import uuid
from typing import Dict, Any, Optional, List

try:
    import pymqi
    IBM_MQ_AVAILABLE = True
except ImportError:
    IBM_MQ_AVAILABLE = False

from .base import JMSProvider, JMSMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Process-level QueueManager connection cache.
#
# pymqi only supports ONE MQI connection per (host, port, queue_manager) tuple
# per OS process.  When a second IBMMQProvider tries to connect to the same
# queue manager it receives MQRC_ALREADY_CONNECTED (2002, CC=WARNING) from
# MQCONNX, and the returned hconn belongs to the *existing* connection — not
# to the newly created QueueManager object (pymqi raises before storing it).
#
# To let multiple IBMMQProvider instances (e.g. qm_dev_local, qm_us_east, …
# all targeting the same physical QM1) share the same live connection, we keep
# a module-level cache keyed by "host:port/queue_manager_name".
# ---------------------------------------------------------------------------
_qm_connection_cache: Dict[str, "pymqi.QueueManager"] = {}
_qm_connection_cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Per-hConn serialization lock.
#
# IBM MQ in CLIENT binding (TCP) mode exposes exactly ONE shared hConn per
# (host:port/qm) per OS process — the same handle is reused by every
# IBMMQProvider that targets the same physical queue manager.
#
# IBM MQ requires that callers SERIALIZE all MQOPEN / MQGET / MQPUT /
# MQCLOSE calls on a shared hConn; concurrent operations from different
# threads produce MQRC_HCONN_ERROR (2018).
#
# Strategy: each put_message / get_message call acquires the per-hConn lock
# before opening a Queue object, performs the single data operation, closes
# the Queue, then releases the lock.  Reconnect logic always runs OUTSIDE
# the lock so other threads are not blocked during the TCP reconnect delay.
# ---------------------------------------------------------------------------
_hconn_operation_locks: Dict[str, threading.Lock] = {}
_hconn_operation_locks_mutex = threading.Lock()   # guards the dict above


def _get_hconn_lock(cache_key: str) -> threading.Lock:
    """Return (creating if necessary) the per-hConn serialization lock."""
    with _hconn_operation_locks_mutex:
        if cache_key not in _hconn_operation_locks:
            _hconn_operation_locks[cache_key] = threading.Lock()
        return _hconn_operation_locks[cache_key]


class IBMMQProvider(JMSProvider):
    """IBM MQ provider implementing JMSProvider interface using pymqi."""

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
        Initialize IBM MQ provider using pymqi.

        Args:
            broker_url: Broker connection string (e.g., 'localhost(1414)')
            channel: Channel name (e.g., 'DEV.APP.SVRCONN')
            username: Username for authentication
            password: Password for authentication
            queue_manager: Queue manager name (e.g., 'QM1')
            ssl_key_store: Path to SSL keystore file (optional)
            ssl_key_store_password: Password for SSL keystore (optional)
        """
        if not IBM_MQ_AVAILABLE:
            raise ImportError("pymqi is not installed. Install with: pip install pymqi==1.12.13")

        self.broker_url = broker_url
        self.channel = channel
        self.queue_manager = queue_manager
        self.username = username
        self.password = password
        self.ssl_key_store = ssl_key_store
        self.ssl_key_store_password = ssl_key_store_password

        self.qm = None
        self._lock = threading.Lock()
        self._reconnect_lock = threading.Lock()  # Serialises concurrent reconnect attempts
        self._connected = False
        self._shared_connection = False  # True when reusing another provider's QM handle

        # Compute the cache key once — used for both the connection cache and
        # the per-hConn operation lock so all providers on the same QM share
        # the same lock object.
        if '(' in self.broker_url and ')' in self.broker_url:
            _host = self.broker_url.split('(')[0]
            _port = int(self.broker_url.split('(')[1].split(')')[0])
        else:
            _host = self.broker_url
            _port = 1414
        self._cache_key = f"{_host}:{_port}/{self.queue_manager}"

        # Auto-connect on initialization
        try:
            self.connect()
        except Exception as e:
            logger.error(f"Failed to connect to IBM MQ: {e}")
            raise

    def connect(self) -> None:
        """Establish connection to IBM MQ queue manager using pymqi."""
        # Serialise concurrent reconnect attempts.  Without this, two threads
        # (e.g. listener + sender) can both call connect() at the same time.
        # Thread A sets self.qm = QueueManager() and is still in connectTCPClient()
        # when Thread B also sets self.qm = QueueManager(). Thread A then stores
        # the new hConn in its local variable, but self.qm already points to B's
        # empty object — leaving B reading a QM with no hConn → "not connected".
        with self._reconnect_lock:
            with self._lock:
                if self._connected and self.qm:
                    logger.debug("Already connected to IBM MQ")
                    return

            max_retries = 5
            retry_delay = 2

            # Parse broker URL once (format: "host(port)")
            if '(' in self.broker_url and ')' in self.broker_url:
                host = self.broker_url.split('(')[0]
                port = int(self.broker_url.split('(')[1].split(')')[0])
            else:
                host = self.broker_url
                port = 1414

            cache_key = f"{host}:{port}/{self.queue_manager}"

            # ------------------------------------------------------------------
            # Fast-path: if another IBMMQProvider in this process already owns a
            # live connection to the same (host, port, queue_manager) tuple,
            # reuse it immediately WITHOUT calling connectTCPClient.
            #
            # This is essential because pymqi only supports ONE MQI connection
            # per queue manager per OS process. Calling MQCONNX a second time:
            #   • returns MQRC_ALREADY_CONNECTED (CC=WARNING) – harmless by itself
            #   • but also partially re-initialises the TLS/SSL layer (GSKit),
            #     leaving it in an undefined state for all later attempts
            # → checking the cache first avoids the SSL pollution entirely.
            # ------------------------------------------------------------------
            with _qm_connection_cache_lock:
                cached_qm = _qm_connection_cache.get(cache_key)

            if cached_qm is not None:
                self.qm = cached_qm
                self._connected = True
                self._shared_connection = True
                logger.info(
                    f"Reusing existing IBM MQ connection for queue manager: "
                    f"{self.queue_manager} via channel {self.channel} "
                    f"(shared connection handle for {cache_key})"
                )
                return

            for attempt in range(max_retries):
                try:
                    # Build in a LOCAL variable so self.qm is never set to a
                    # partially-initialised object that other threads could see.
                    # Only assign to self.qm once connectTCPClient succeeds and
                    # we have a real hConn.
                    new_qm = pymqi.QueueManager(None)

                    # Build conn_info string — pymqi expects "host(port)" as a
                    # single positional argument, not separate host/port values.
                    # The second argument must be a CD() (channel definition)
                    # struct, not MQCNO_NONE (a connection options flag).
                    # user and password are the 5th and 6th positional args;
                    # passing user= as a keyword on top of positional causes
                    # "multiple values for argument 'user'".
                    conn_info = f"{host}({port})"
                    new_qm.connectTCPClient(
                        self.queue_manager,
                        pymqi.CD(),
                        self.channel,
                        conn_info,
                        self.username,
                        self.password,
                    )

                    # connectTCPClient succeeded → safe to publish the handle
                    self.qm = new_qm
                    self._connected = True
                    self._shared_connection = False
                    # Cache this connection for other providers targeting the same QM
                    with _qm_connection_cache_lock:
                        _qm_connection_cache[cache_key] = self.qm
                    logger.info(f"Connected to IBM MQ queue manager: {self.queue_manager} at {host}:{port}")
                    return

                except pymqi.MQMIError as e:
                    # MQRC_ALREADY_CONNECTED (CC=WARNING): IBM MQ returns the
                    # existing hConn IN new_qm even when raising this exception.
                    # Using new_qm directly avoids the 2-second retry delay that
                    # would otherwise occur when the server disconnects an idle
                    # channel and the MQ client library still tracks the old hConn.
                    if e.reason == pymqi.CMQC.MQRC_ALREADY_CONNECTED and e.comp == pymqi.CMQC.MQCC_WARNING:
                        # new_qm.handle already contains the valid existing hConn
                        self.qm = new_qm
                        self._connected = True
                        self._shared_connection = False
                        with _qm_connection_cache_lock:
                            _qm_connection_cache[cache_key] = self.qm
                        logger.info(
                            f"Connected to IBM MQ queue manager: {self.queue_manager} at {host}:{port} "
                            f"(reused existing hConn after ALREADY_CONNECTED)"
                        )
                        return
                    logger.warning(
                        f"Connection attempt {attempt + 1}/{max_retries} failed: {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                    # Do NOT touch self.qm here — leave it at whatever valid state
                    # it was in before this connect() call (None or the old handle).

                except Exception as e:
                    logger.warning(
                        f"Connection attempt {attempt + 1}/{max_retries} failed: {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                    # Same: leave self.qm untouched on non-MQ exceptions.

            raise ConnectionError(f"Failed to connect to IBM MQ after {max_retries} attempts")

    def disconnect(self) -> None:
        """Close connection to IBM MQ queue manager."""
        with self._lock:
            if self.qm:
                if self._shared_connection:
                    # This provider is reusing another provider's connection handle.
                    # Do NOT disconnect — the owning provider manages the lifecycle.
                    logger.debug(
                        f"Skipping disconnect for {self.queue_manager} "
                        f"(shared connection handle, managed by original owner)"
                    )
                    self.qm = None
                    self._connected = False
                    return
                try:
                    self.qm.disconnect()
                    logger.info("Disconnected from IBM MQ")
                except Exception as e:
                    logger.warning(f"Error disconnecting from IBM MQ: {e}")
                finally:
                    self.qm = None
                    self._connected = False

    def is_connected(self) -> bool:
        """Check if connection is active."""
        with self._lock:
            return self._connected and self.qm is not None

    def put_message(
        self,
        destination: str,
        payload: str,
        headers: Optional[Dict[str, str]] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not self.is_connected():
            raise ConnectionError("Not connected to IBM MQ")

        _connection_loss = {
            pymqi.CMQC.MQRC_HCONN_ERROR,           # 2018 – handle invalid
            pymqi.CMQC.MQRC_CONNECTION_BROKEN,      # 2009 – TCP broken
            pymqi.CMQC.MQRC_Q_MGR_NOT_AVAILABLE,    # 2059 – QM stopping
            pymqi.CMQC.MQRC_Q_MGR_QUIESCING,        # 2161 – QM quiescing
        }

        op_lock = _get_hconn_lock(self._cache_key)

        for attempt in range(2):
            queue = None
            qm_snapshot = self.qm
            need_reconnect = False

            # Acquire the per-hConn lock for the entire MQOPEN→MQPUT→MQCLOSE
            # sequence.  Reconnect happens OUTSIDE the lock so other threads
            # are not blocked during the TCP re-connect delay.
            with op_lock:
                try:
                    md = pymqi.MD()
                    if headers and "X-Correlation-ID" in headers:
                        corr_id = headers["X-Correlation-ID"]
                        md['CorrelId'] = corr_id.encode().ljust(24, b'\x00')[:24]

                    queue = pymqi.Queue(qm_snapshot, destination)
                    queue.put(payload, md)
                    return uuid.uuid4().hex

                except pymqi.MQMIError as e:
                    if e.reason in _connection_loss and attempt == 0:
                        logger.warning(
                            f"IBM MQ connection lost while putting to {destination} "
                            f"(MQRC {e.reason}). Invalidating and reconnecting..."
                        )
                        self._invalidate_connection(stale_qm=qm_snapshot)
                        need_reconnect = True
                    else:
                        logger.error(f"Failed to put message to {destination}: {e}")
                        raise

                except Exception as e:
                    _is_handle_error = "not connected" in str(e).lower() or "not open" in str(e).lower()
                    if _is_handle_error and attempt == 0:
                        logger.warning(
                            f"IBM MQ handle invalid while putting to {destination} "
                            f"({type(e).__name__}: {e}). Invalidating and reconnecting..."
                        )
                        self._invalidate_connection(stale_qm=qm_snapshot)
                        need_reconnect = True
                    else:
                        logger.error(f"Failed to put message to {destination}: {e}")
                        raise

                finally:
                    if queue is not None:
                        try:
                            queue.close()
                        except Exception:
                            pass

            # Outside the lock: reconnect then loop back for attempt 1
            if need_reconnect:
                try:
                    self.connect()
                    logger.info("Reconnected to IBM MQ successfully, retrying put...")
                except Exception as reconnect_err:
                    logger.error(f"IBM MQ reconnect failed: {reconnect_err}")
                    raise

        raise RuntimeError(f"put_message to {destination} failed after 2 attempts")

    def _invalidate_connection(self, stale_qm=None) -> None:
        """
        Mark this connection as invalid and evict it from the process-level cache.

        Args:
            stale_qm: The QueueManager handle that was in use when the error
                      occurred (i.e. the handle the caller snapshotted before
                      opening a Queue).  If provided, invalidation is skipped
                      when another thread has already replaced self.qm with a
                      fresh connection — preventing the new connection from
                      being torn down by a racing thread.

        Call this whenever IBM MQ signals the hConn is no longer usable
        (MQRC_HCONN_ERROR 2018, MQRC_CONNECTION_BROKEN 2009, MQRC_Q_MGR_NOT_AVAILABLE 2059).
        The next connect() call will open a fresh TCP link instead of reusing
        the now-stale cached handle.
        """
        with self._lock:
            # Guard: only invalidate when we are still on the same (broken) handle.
            # If another thread already reconnected, self.qm points to a brand-new
            # QueueManager — disconnecting it here would destroy the new connection.
            if stale_qm is not None and self.qm is not stale_qm:
                logger.debug(
                    "IBM MQ connection already replaced by another thread "
                    "— skipping invalidation to preserve the new connection"
                )
                return
            old_qm = self.qm
            was_shared = self._shared_connection
            self._connected = False
            self.qm = None
            self._shared_connection = False

        # Call MQDISC on the old handle so the MQ client library releases the
        # process-level "already connected" tracking entry.  Without this, the
        # very next MQCONNX call returns MQRC_ALREADY_CONNECTED (2002, CC=WARNING)
        # which causes an unnecessary 2-second retry delay in connect().
        # The call will almost certainly fail (the hConn is broken), but that is
        # expected and harmless — we just want the client-side cleanup.
        # NOTE: Shared-connection providers do NOT call disconnect — they do not
        # own the handle.  Calling disconnect on a shared handle would destroy the
        # owner's live connection and leave other shared providers in a broken state.
        if old_qm is not None and not was_shared:
            try:
                old_qm.disconnect()
                logger.debug("Disconnected stale IBM MQ handle during invalidation")
            except Exception:
                pass  # Expected when the TCP connection is already broken

        if '(' in self.broker_url and ')' in self.broker_url:
            host = self.broker_url.split('(')[0]
            port = int(self.broker_url.split('(')[1].split(')')[0])
        else:
            host = self.broker_url
            port = 1414

        cache_key = f"{host}:{port}/{self.queue_manager}"

        # Only evict the cache entry when this provider OWNS the connection
        # (was_shared=False).  A shared-connection provider must NOT evict the
        # cache because the entry belongs to the owning provider — evicting it
        # would cause the owner's next connect() to issue a redundant MQCONNX
        # and get MQRC_ALREADY_CONNECTED, adding an unwanted reconnect cycle.
        if not was_shared:
            with _qm_connection_cache_lock:
                # Evict only our own entry; another thread may have already
                # stored a fresh QM in the cache.
                if _qm_connection_cache.get(cache_key) is old_qm:
                    _qm_connection_cache.pop(cache_key, None)
            logger.debug(f"Evicted stale IBM MQ connection from cache: {cache_key}")
        else:
            logger.debug(
                f"Shared-connection invalidated for {cache_key} — cache entry preserved"
            )

    def get_message(
        self,
        destination: str,
        timeout_ms: int = 1000,
        max_messages: int = 1,
        no_wait: bool = False,
    ) -> List[JMSMessage]:
        """
        Retrieve messages from a JMS queue.

        Uses no_wait=True in the JMS listener to avoid the IBM MQ restriction
        of only one pending MQGET-with-wait per hConn.  All callers (listener,
        tests, consume()) share the same hConn, so they serialize via the
        per-hConn operation lock (_get_hconn_lock) rather than blocking each
        other with a long MQGMO_WAIT.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to IBM MQ")

        messages = []
        op_lock = _get_hconn_lock(self._cache_key)
        need_reconnect = False

        _connection_loss = {
            pymqi.CMQC.MQRC_HCONN_ERROR,           # 2018 – handle invalid
            pymqi.CMQC.MQRC_CONNECTION_BROKEN,      # 2009 – TCP broken
            pymqi.CMQC.MQRC_Q_MGR_NOT_AVAILABLE,    # 2059 – QM stopping
            pymqi.CMQC.MQRC_Q_MGR_QUIESCING,        # 2161 – QM quiescing
        }
        _silent = {
            pymqi.CMQC.MQRC_UNKNOWN_OBJECT_NAME,    # 2085 – queue not yet created
            pymqi.CMQC.MQRC_NOT_AUTHORIZED,         # 2035 – permissions
        }

        qm_snapshot = self.qm

        with op_lock:
            queue = None
            try:
                gmo = pymqi.GMO()
                if no_wait:
                    gmo['Options'] = pymqi.CMQC.MQGMO_NO_WAIT | pymqi.CMQC.MQGMO_FAIL_IF_QUIESCING
                else:
                    gmo['Options'] = pymqi.CMQC.MQGMO_WAIT | pymqi.CMQC.MQGMO_FAIL_IF_QUIESCING
                    gmo['WaitInterval'] = timeout_ms

                queue = pymqi.Queue(qm_snapshot, destination)

                for _ in range(max_messages):
                    try:
                        md = pymqi.MD()
                        msg_bytes = queue.get(None, md, gmo)

                        try:
                            payload = msg_bytes.decode('utf-8')
                        except UnicodeDecodeError:
                            payload = msg_bytes.hex()

                        corr_id = md['CorrelId']
                        messages.append(JMSMessage(
                            destination=destination,
                            payload=payload,
                            properties={
                                "CorrelId": corr_id.strip(b'\x00').decode('utf-8', errors='ignore') if corr_id else None
                            }
                        ))
                    except pymqi.MQMIError as e:
                        if e.reason == pymqi.CMQC.MQRC_NO_MSG_AVAILABLE:
                            break
                        raise  # caught by the outer MQMIError handler below

            except pymqi.MQMIError as e:
                if e.reason in _connection_loss:
                    logger.warning(
                        f"IBM MQ connection lost while polling {destination} "
                        f"(MQRC {e.reason}). Invalidating and reconnecting..."
                    )
                    self._invalidate_connection(stale_qm=qm_snapshot)
                    need_reconnect = True
                elif e.reason in _silent:
                    logger.debug(f"Queue {destination} not accessible yet (MQRC {e.reason}): {e}")
                else:
                    logger.warning(f"Failed to get message from {destination}: {e}")

            except Exception as e:
                _is_handle_error = "not connected" in str(e).lower() or "not open" in str(e).lower()
                if _is_handle_error:
                    logger.warning(
                        f"IBM MQ handle invalid while polling {destination} "
                        f"({type(e).__name__}: {e}). Invalidating and reconnecting..."
                    )
                    self._invalidate_connection(stale_qm=qm_snapshot)
                    need_reconnect = True
                else:
                    logger.warning(f"Failed to get message from {destination}: {e}")

            finally:
                if queue is not None:
                    try:
                        queue.close()
                    except Exception:
                        pass

        # Outside the lock: reconnect if needed; the NEXT poll will use the fresh hConn.
        if need_reconnect:
            try:
                self.connect()
                logger.info("Reconnected to IBM MQ successfully")
            except Exception as reconnect_err:
                logger.error(f"IBM MQ reconnect failed: {reconnect_err}")

        return messages

    def consume(
        self,
        destination: str,
        limit: int = 100,
        timeout_ms: int = 5000,
    ) -> List[Dict[str, Any]]:
        """
        Consume messages from a JMS queue and return them as dicts.

        Uses a polling loop with MQGMO_NO_WAIT to avoid conflicting with the
        JMS listener's concurrent MQGET-with-wait on the shared HCONN.
        IBM MQ only permits ONE pending MQGET-with-wait per HCONN; using
        MQGMO_NO_WAIT and sleeping between polls side-steps this limit entirely.

        Args:
            destination: Queue name to read from
            limit: Maximum number of messages to retrieve (default 100)
            timeout_ms: Total time budget in milliseconds (default 5000)

        Returns:
            List of message dicts with keys: value, timestamp, partition,
            offset, headers, key
        """
        POLL_INTERVAL_S = 0.1   # sleep 100 ms between empty polls
        deadline = time.time() + timeout_ms / 1000.0
        all_jms = []

        while time.time() < deadline and len(all_jms) < limit:
            # Use no_wait=True so we never block the shared HCONN while the
            # listener may already have a pending MQGMO_WAIT on another queue.
            batch = self.get_message(
                destination,
                timeout_ms=0,
                max_messages=limit - len(all_jms),
                no_wait=True,
            )
            all_jms.extend(batch)

            if not batch:
                # No messages yet — sleep a little then retry
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                time.sleep(min(POLL_INTERVAL_S, remaining))

        result = []
        for msg in all_jms:
            result.append({
                "value": msg.payload,
                "timestamp": 0,      # JMS does not expose a delivery timestamp here
                "partition": 0,      # N/A for JMS
                "offset": 0,         # N/A for JMS
                "headers": msg.headers,
                "key": None,
            })
        return result

    def validate_connection(self) -> bool:
        """Test if connection is valid and responsive."""
        if not self.is_connected():
            return False

        try:
            # Try to inquire queue manager to validate connection
            self.qm.inquireQueueManager([pymqi.CMQC.MQCA_Q_MGR_NAME])
            return True
        except Exception as e:
            logger.debug(f"Connection validation failed: {e}")
            return False

    def get_destination_stats(self, destination: str) -> Dict[str, Any]:
        """Get statistics for a queue."""
        if not self.is_connected():
            return {"error": "Not connected"}

        try:
            # Open queue for inquiring
            queue = pymqi.Queue(self.qm, destination, pymqi.CMQC.MQOO_INQUIRE)
            try:
                # Get queue depth
                queue_info = queue.inquireQueue([pymqi.CMQC.MQIA_CURRENT_Q_DEPTH])
                depth = queue_info.get(pymqi.CMQC.MQIA_CURRENT_Q_DEPTH, 0)
                return {
                    "name": destination,
                    "depth": depth,
                    "type": "queue"
                }
            finally:
                queue.close()
        except Exception as e:
            logger.debug(f"Failed to get stats for {destination}: {e}")
            return {"name": destination, "depth": "unknown", "error": str(e)}

    def list_destinations(self) -> List[str]:
        """List all available queues on the queue manager."""
        if not self.is_connected():
            return []

        destinations = []

        try:
            # Queue enumeration not fully implemented for IBM MQ
            logger.debug("Queue enumeration not fully implemented for IBM MQ")
        except Exception as e:
            logger.debug(f"Failed to list queues: {e}")

        return destinations

    def close(self) -> None:
        """Close connection and cleanup resources."""
        self.disconnect()
