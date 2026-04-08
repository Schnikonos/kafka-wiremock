"""
Debug endpoint for topics metadata.
"""
import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug", tags=["debug"])

# Global references - will be set by main.py
_listener_engine = None
_message_cache = None


def set_listener_engine(engine):
    """Set the global listener engine reference."""
    global _listener_engine
    _listener_engine = engine


def set_message_cache(cache):
    """Set the global message cache reference."""
    global _message_cache
    _message_cache = cache


@router.get("/topics")
async def debug_topics() -> Dict[str, Any]:
    """
    Debug endpoint: Show all discovered topics and their metadata.

    Returns:
        List of all topics with their types, existence status, and other metadata
    """
    try:
        if not _listener_engine or not _listener_engine.topic_metadata_manager:
            return {
                "success": False,
                "message": "Topic metadata manager not available"
            }

        summary = _listener_engine.topic_metadata_manager.get_metadata_summary()

        # Get consumer subscription status
        consumer_subscription = []
        if _listener_engine.consumer:
            try:
                consumer_subscription = list(_listener_engine.consumer.subscription() or [])
            except Exception as e:
                logger.debug(f"Error getting consumer subscription: {e}")

        return {
            "success": True,
            "total_topics": summary["total_topics"],
            "consumer_subscribed": sorted(consumer_subscription),
            "topics": summary["topics"],
            "cache_stats": _message_cache.get_cache_stats() if _message_cache else None
        }

    except Exception as e:
        logger.error(f"Error in debug topics: {e}")
        return {
            "success": False,
            "error": str(e)
        }

