"""
Debug endpoint for message cache statistics.
"""
import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug", tags=["debug"])

# Global reference - will be set by main.py
_message_cache = None


def set_message_cache(cache):
    """Set the global message cache reference."""
    global _message_cache
    _message_cache = cache


@router.get("/cache")
async def debug_cache() -> Dict[str, Any]:
    """
    Debug endpoint: Show message cache statistics and contents.

    Returns:
        Cache statistics including message counts, consumption status, and formats
    """
    try:
        if not _message_cache:
            raise HTTPException(status_code=503, detail="Message cache not initialized")

        return {
            "success": True,
            "cache_stats": _message_cache.get_cache_stats(),
            "ttl_seconds": _message_cache.ttl_seconds
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in debug cache: {e}")
        return {
            "success": False,
            "error": str(e)
        }

