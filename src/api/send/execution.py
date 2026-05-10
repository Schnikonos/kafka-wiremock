"""
Send execution endpoints.
"""
import logging
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/send", tags=["send"])

# Global references - will be set by main.py
_send_loader = None
_send_executor = None


def set_send_loader(loader):
    """Set the global send loader reference."""
    global _send_loader
    _send_loader = loader


def set_send_executor(executor):
    """Set the global send executor reference."""
    global _send_executor
    _send_executor = executor


def _convert_send_result_to_dict(result) -> Dict[str, Any]:
    """Convert a SendResult object to a JSON-serializable dictionary."""
    return {
        "send_id": result.send_id,
        "status": result.status,
        "elapsed_ms": result.elapsed_ms,
        "injected": result.injected,
        "errors": result.errors
    }


@router.post("/{send_id}")
async def run_send(
    send_id: str,
    verbose: bool = Query(False, description="If true, include detailed injection logs")
) -> Dict[str, Any]:
    """
    Run a send definition.

    Args:
        send_id: Send identifier
        verbose: If true, include detailed logs

    Returns:
        Send execution result
    """
    if not _send_loader:
        raise HTTPException(status_code=503, detail="Send loader not initialized")
    if not _send_executor:
        raise HTTPException(status_code=503, detail="Send executor not initialized")

    try:
        # Find the send definition
        sends = _send_loader.discover_sends()
        send = next((s for s in sends if s.name == send_id), None)
        if not send:
            raise HTTPException(status_code=404, detail=f"Send not found: {send_id}")

        # Execute the send
        result = await _send_executor.run_send(send, verbose=verbose)
        return _convert_send_result_to_dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running send {send_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

