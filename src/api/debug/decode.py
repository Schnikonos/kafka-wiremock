"""
Debug endpoint for message decoding.
"""
import logging
import base64
from typing import Dict, Any, Union
from fastapi import APIRouter, HTTPException, Body

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug", tags=["debug"])

# Global reference - will be set by main.py
_listener_engine = None


def set_listener_engine(engine):
    """Set the global listener engine reference."""
    global _listener_engine
    _listener_engine = engine


@router.post("/decode")
async def debug_decode(
    topic: str = Body(..., description="Kafka topic name"),
    payload: Union[str, bytes] = Body(..., description="Message payload (base64 encoded bytes or JSON/string)")
) -> Dict[str, Any]:
    """
    Debug endpoint: Decode a message and show format detection.

    Args:
        topic: Topic name (used to determine expected format from metadata)
        payload: Raw message bytes (base64 encoded) or string/JSON

    Returns:
        Decoded message, detected format, and deserialization details
    """
    try:
        if not _listener_engine:
            raise HTTPException(status_code=503, detail="Listener engine not initialized")

        # Handle payload encoding
        raw_bytes = None
        if isinstance(payload, str):
            try:
                # Try to decode as base64 first
                raw_bytes = base64.b64decode(payload, validate=True)
            except Exception:
                # Fall back to UTF-8 encoding
                raw_bytes = payload.encode('utf-8')
        else:
            raw_bytes = payload

        # Get topic metadata
        topic_type = "json"
        if _listener_engine.topic_metadata_manager:
            topic_type = _listener_engine.topic_metadata_manager.get_topic_type(topic)

        # Deserialize
        decoded, fmt = _listener_engine._deserialize_message(
            type('MockMessage', (), {'value': raw_bytes})(),
            topic_type
        )

        # Get schema registry info if available
        schema_registry_status = None
        if _listener_engine.schema_registry:
            schema_registry_status = _listener_engine.schema_registry.get_cache_stats()

        return {
            "success": True,
            "topic": topic,
            "expected_format": topic_type,
            "detected_format": fmt,
            "decoded_value": decoded,
            "payload_size_bytes": len(raw_bytes),
            "schema_registry": schema_registry_status
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in debug decode: {e}")
        return {
            "success": False,
            "error": str(e),
            "topic": topic,
            "payload_size_bytes": len(raw_bytes) if 'raw_bytes' in locals() else 0
        }

