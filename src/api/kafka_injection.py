"""
Message injection and consumption endpoints (Kafka and JMS).
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Header, Query
from .models import InjectMessageRequest, InjectMessageResponse, ConsumedMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["messaging"])

# Global references - will be set by main.py
_kafka_client = None
_jms_registry = None  # NEW: registry instead of single client
_config_loader = None
_jms_config_loader = None  # NEW
_message_cache = None  # cache populated by background listeners


def set_kafka_client(client):
    """Set the global Kafka client reference."""
    global _kafka_client
    _kafka_client = client


def set_jms_registry(registry):  # NEW: registry setter
    """Set the global JMS client registry reference."""
    global _jms_registry
    _jms_registry = registry


def set_config_loader(loader):
    """Set the global config loader reference."""
    global _config_loader
    _config_loader = loader


def set_jms_config_loader(loader):  # NEW
    """Set the global JMS config loader reference."""
    global _jms_config_loader
    _jms_config_loader = loader


def set_message_cache(cache):
    """Set the global message cache reference (populated by background listeners)."""
    global _message_cache
    _message_cache = cache


@router.post("/inject/{destination}", response_model=InjectMessageResponse)
async def inject_message(
    destination: str,
    request: InjectMessageRequest,
    msg_type: str = Query("kafka", description="Message type: 'kafka' or 'jms'"),
    queue_manager: str = Query(None, description="(JMS only) Queue manager reference"),  # NEW
    schema_id: Optional[int] = Header(None, alias="schema-id"),
) -> InjectMessageResponse:
    """
    Inject a message into a Kafka topic or JMS queue.
    Args:
        destination: Target Kafka topic or JMS queue name
        request: Message and optional schema info
        msg_type: Message type ('kafka' or 'jms', default: 'kafka')
        queue_manager: (JMS only) Queue manager reference to use
        schema_id: Optional schema ID header for AVRO (Kafka only)
    Returns:
        InjectMessageResponse with message ID
    """
    msg_type = msg_type.lower()

    if msg_type == "jms":
        if not _jms_registry or _jms_registry.is_empty():  # NEW: check registry
            raise HTTPException(status_code=503, detail="JMS client(s) not initialized")
        try:
            message = request.message
            if message is None:
                raise HTTPException(status_code=400, detail="Message is required")

            # NEW: Get the correct client from registry
            try:
                client = _jms_registry.get_client(queue_manager)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            message_id = client.put_message(
                destination=destination,
                payload=json.dumps(message) if isinstance(message, dict) else str(message),
                headers=request.headers if hasattr(request, "headers") else None,
            )
            if message_id is None:
                raise HTTPException(
                    status_code=500, detail="Failed to produce message to JMS queue"
                )
            return InjectMessageResponse(
                message_id=message_id,
                topic=destination,
                status="success",
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error injecting message to JMS queue {destination}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Default to Kafka
        if not _kafka_client:
            raise HTTPException(status_code=503, detail="Kafka client not initialized")
        try:
            message = request.message
            if message is None:
                raise HTTPException(status_code=400, detail="Message is required")

            message_id = _kafka_client.produce(
                topic=destination, message=message, schema_id=schema_id
            )
            if message_id is None:
                raise HTTPException(
                    status_code=500, detail="Failed to produce message to Kafka"
                )
            return InjectMessageResponse(
                message_id=message_id,
                topic=destination,
                status="success",
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error injecting message to {destination}: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/{destination}", response_model=List[ConsumedMessage])
async def get_messages(
    destination: str,
    msg_type: str = Query("kafka", description="Message type: 'kafka' or 'jms'"),
    queue_manager: str = Query(None, description="(JMS only) Queue manager reference"),  # NEW
    limit: int = Query(10, ge=1, le=100),
    timeout_ms: int = Query(
        500, ge=1, le=30000, description="Total polling timeout in milliseconds (default: 500)"
    ),
    poll_interval_ms: int = Query(
        100,
        ge=1,
        le=5000,
        description="Individual poll interval in milliseconds (default: 100)",
    ),
    since_ms: int = Query(
        None,
        description=(
            "Only return messages cached after this Unix epoch timestamp in milliseconds. "
            "Useful for paging: pass the timestamp of the last message you received to "
            "avoid re-fetching old ones.  Only applies when the message cache is available."
        ),
    ),
) -> List[ConsumedMessage]:
    """
    Retrieve messages from a Kafka topic or JMS queue.
    Args:
        destination: Kafka topic or JMS queue name
        msg_type: Message type ('kafka' or 'jms', default: 'kafka')
        queue_manager: (JMS only) Queue manager reference to use
        limit: Maximum number of messages to retrieve (default: 10, max: 100)
        timeout_ms: Total polling timeout in milliseconds (default: 500)
        poll_interval_ms: Duration of each individual poll in milliseconds (default: 100)
        since_ms: Only return messages cached after this Unix epoch milliseconds timestamp
    Returns:
        List of consumed messages
    """
    msg_type = msg_type.lower()

    if msg_type == "jms":
        if not _jms_registry or _jms_registry.is_empty():  # NEW: check registry
            raise HTTPException(status_code=503, detail="JMS client(s) not initialized")
        try:
            # Serve from cache when available (populated by JMS listener background thread)
            if _message_cache is not None:
                since_s = (since_ms / 1000.0) if since_ms is not None else None
                cached = _message_cache.get_messages(destination, since=since_s)
                if cached:
                    result = []
                    for m in cached[-limit:]:
                        result.append(ConsumedMessage(
                            topic=destination,
                            partition=m.partition,
                            offset=m.offset,
                            key=m.key,
                            value=m.value,
                            headers=m.headers or {},
                            timestamp=m.timestamp,
                        ))
                    return result

            # NEW: Get the correct client from registry
            try:
                client = _jms_registry.get_client(queue_manager)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            messages = client.consume(
                destination=destination, limit=limit, timeout_ms=timeout_ms
            )
            result = []
            for msg in messages:
                if "error" not in msg:
                    result.append(ConsumedMessage(**msg))
            return result
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error consuming messages from JMS queue {destination}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Default to Kafka
        if not _kafka_client:
            raise HTTPException(status_code=503, detail="Kafka client not initialized")
        try:
            # Serve from cache when available (populated by KafkaListenerEngine background thread).
            # The cache path is near-zero latency; fall back to direct polling only when
            # the topic is not yet covered by the listener.
            if _message_cache is not None:
                since_s = (since_ms / 1000.0) if since_ms is not None else None
                cached = _message_cache.get_messages(destination, since=since_s)
                if cached:
                    result = []
                    for m in cached[-limit:]:
                        result.append(ConsumedMessage(
                            topic=destination,
                            partition=m.partition,
                            offset=m.offset,
                            key=m.key,
                            value=m.value,
                            headers=m.headers or {},
                            timestamp=m.timestamp,
                        ))
                    return result

            messages = _kafka_client.consume_latest(
                topic=destination,
                max_messages=limit,
                timeout_ms=timeout_ms,
                poll_interval_ms=poll_interval_ms,
            )
            result = []
            for msg in messages:
                if "error" not in msg:
                    result.append(ConsumedMessage(**msg))
            return result
        except Exception as e:
            logger.error(f"Error consuming messages from {destination}: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/jms/pool-stats")  # NEW
async def get_jms_pool_stats():
    """
    Get connection pool statistics for all JMS queue managers. (NEW)

    Returns:
        Dictionary with pool statistics
    """
    if not _jms_registry or _jms_registry.is_empty():
        raise HTTPException(status_code=503, detail="JMS not configured")

    try:
        stats = _jms_registry.get_pool_stats()
        return {
            "status": "ok",
            "pools": stats,
            "pooling_enabled": _jms_registry.enable_pooling,
        }
    except Exception as e:
        logger.error(f"Error getting pool stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
