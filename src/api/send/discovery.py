"""
Send discovery and definition endpoints.
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from ...send.loader import SendDefinition
from ...test.loader import TestInjection, TestScript

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/send", tags=["send"])

# Global reference - will be set by main.py
_send_loader = None


def set_send_loader(loader):
    """Set the global send loader reference."""
    global _send_loader
    _send_loader = loader


@router.get("")
async def list_sends(tags: Optional[str] = Query(None, description="Comma-separated tags to filter by")) -> Dict[str, Any]:
    """
    List all discovered send definitions.

    Args:
        tags: Comma-separated tag list to filter sends

    Returns:
        Dictionary with send metadata
    """
    if not _send_loader:
        raise HTTPException(status_code=503, detail="Send loader not initialized")

    try:
        sends = _send_loader.discover_sends()

        # Filter by tags if provided
        if tags:
            tag_list = [t.strip() for t in tags.split(",")]
            sends = _send_loader.get_sends_by_tag(sends, tag_list)

        result = []
        for send in sends:
            injection_count = sum(1 for item in send.items if isinstance(item, TestInjection))
            script_count = sum(1 for item in send.items if isinstance(item, TestScript))
            result.append({
                "send_id": send.name,
                "priority": send.priority,
                "tags": send.tags,
                "skip": send.skip,
                "timeout_ms": send.timeout_ms,
                "injections": injection_count,
                "scripts": script_count
            })

        response = {
            "total": len(result),
            "sends": result
        }

        return response
    except Exception as e:
        logger.error(f"Error listing sends: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{send_id}")
async def get_send_definition(send_id: str) -> Dict[str, Any]:
    """
    Get parsed send definition.

    Args:
        send_id: Send identifier (from send name)

    Returns:
        Send definition as dictionary
    """
    if not _send_loader:
        raise HTTPException(status_code=503, detail="Send loader not initialized")

    try:
        sends = _send_loader.discover_sends()
        send = next((s for s in sends if s.name == send_id), None)
        if not send:
            raise HTTPException(status_code=404, detail=f"Send not found: {send_id}")

        return {
            "name": send.name,
            "priority": send.priority,
            "tags": send.tags,
            "skip": send.skip,
            "timeout_ms": send.timeout_ms,
            "injections": [
                {
                    "message_id": inj.message_id,
                    "topic": inj.topic,
                    "has_headers": inj.headers is not None and len(inj.headers) > 0,
                    "has_key": inj.key is not None,
                    "delay_ms": inj.delay_ms,
                    "has_fault": inj.fault is not None
                }
                for inj in send.items if isinstance(inj, TestInjection)
            ],
            "has_scripts": any(isinstance(item, TestScript) for item in send.items)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving send {send_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

