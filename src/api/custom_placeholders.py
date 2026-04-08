"""
Custom placeholders endpoints.
"""
import logging
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["custom-placeholders"])

# Global reference - will be set by main.py
_custom_placeholder_registry = None


def set_custom_placeholder_registry(registry):
    """Set the global custom placeholder registry reference."""
    global _custom_placeholder_registry
    _custom_placeholder_registry = registry


@router.get("/custom-placeholders")
async def get_custom_placeholders():
    """
    Get all custom placeholders with their metadata.

    Returns:
        List of custom placeholders with execution order
    """
    if not _custom_placeholder_registry:
        raise HTTPException(status_code=503, detail="Custom placeholder registry not initialized")

    try:
        placeholders = _custom_placeholder_registry.get_all_placeholders()
        order_map = _custom_placeholder_registry.placeholder_order

        result = []
        for name, func in placeholders.items():
            order_priority = order_map.get(name)
            result.append({
                "name": name,
                "order": order_priority,
                "docstring": func.__doc__ or ""
            })

        # Sort by execution order
        result.sort(key=lambda x: (x["order"] is not None, x["order"] or 0))

        return result
    except Exception as e:
        logger.error(f"Error retrieving custom placeholders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

