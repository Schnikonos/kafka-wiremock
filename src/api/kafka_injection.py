"""
Kafka message injection and consumption endpoints.
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Header, Query
from .models import InjectMessageRequest, InjectMessageResponse, ConsumedMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["kafka"])

# Global reference - will be set by main.py
_kafka_client = None


def set_kafka_client(client):
    """Set the global Kafka client reference."""
    global _kafka_client
    _kafka_client = client


@router.post("/inject/{topic}", response_model=InjectMessageResponse)
async def inject_message(
    topic: str,
    request: InjectMessageRequest,
    schema_id: Optional[int] = Header(None, alias="schema-id"),
) -> InjectMessageResponse:
    """
    Inject a message into a Kafka topic.
    Args:
        topic: Target Kafka topic
        request: Message and optional schema info
        schema_id: Optional schema ID header for AVRO
    Returns:
        InjectMessageResponse with message ID
    """
    if not _kafka_client:
        raise HTTPException(status_code=503, detail="Kafka client not initialized")
    try:
        # Get message from request
        message = request.message
        if message is None:
            raise HTTPException(status_code=400, detail="Message is required")
        # Produce to Kafka
        message_id = _kafka_client.produce(
            topic=topic,
            message=message,
            schema_id=schema_id
        )
        if message_id is None:
            raise HTTPException(status_code=500, detail="Failed to produce message to Kafka")
        return InjectMessageResponse(
            message_id=message_id,
            topic=topic,
            status="success"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error injecting message to {topic}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/{topic}", response_model=List[ConsumedMessage])
async def get_messages(
    topic: str,
    limit: int = Query(10, ge=1, le=100),
    timeout_ms: int = Query(500, ge=1, le=30000, description="Total polling timeout in milliseconds (default: 500)"),
    poll_interval_ms: int = Query(100, ge=1, le=5000, description="Individual poll interval in milliseconds (default: 100)"),
) -> List[ConsumedMessage]:
    """
    Retrieve messages from a Kafka topic.
    Args:
        topic: Kafka topic to consume from
        limit: Maximum number of messages to retrieve (default: 10, max: 100)
        timeout_ms: Total time budget for polling in milliseconds (default: 500)
        poll_interval_ms: Duration of each individual poll in milliseconds (default: 100)
    Returns:
        List of consumed messages
    """
    if not _kafka_client:
        raise HTTPException(status_code=503, detail="Kafka client not initialized")
    try:
        # Consume latest messages
        messages = _kafka_client.consume_latest(topic=topic, max_messages=limit,
                                               timeout_ms=timeout_ms, poll_interval_ms=poll_interval_ms)
        # Convert to response format
        result = []
        for msg in messages:
            if "error" not in msg:
                result.append(ConsumedMessage(**msg))
        return result
    except Exception as e:
        logger.error(f"Error consuming messages from {topic}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

