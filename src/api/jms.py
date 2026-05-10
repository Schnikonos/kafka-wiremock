"""
JMS Listener control API endpoints.

Allows operators to inspect, start/stop the JMS listener engine and
pause/resume listening on individual JMS queues without losing messages
(messages remain on the broker queue while the listener is paused).
"""
import logging
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter()

# Global reference set by main.py
_jms_listener_engine = None


def set_jms_listener_engine(engine) -> None:
    """Set the JMS listener engine reference (called from main.py)."""
    global _jms_listener_engine
    _jms_listener_engine = engine


# ---------------------------------------------------------------------------
# Listener engine endpoints
# ---------------------------------------------------------------------------

@router.get("/jms/listener", tags=["JMS"])
async def get_listener_status():
    """
    Get the current status of the JMS listener engine.

    Returns running state, poll interval, and per-queue status.
    """
    if _jms_listener_engine is None:
        return {
            "running": False,
            "active_queues": [],
            "paused_queues": [],
            "listening_queues": [],
            "poll_interval_ms": 100,
            "note": "JMS listener not initialised (no queue managers configured)"
        }
    return _jms_listener_engine.get_listener_status()


@router.post("/jms/listener/start", tags=["JMS"])
async def start_listener():
    """
    Start the JMS listener engine if it is not already running.

    Messages that arrived while the listener was stopped are NOT
    replayed — they remain in the broker queue and will be picked up
    once the listener is active again.
    """
    if _jms_listener_engine is None:
        raise HTTPException(status_code=503, detail="JMS listener not initialised")

    if _jms_listener_engine.is_running():
        return {"status": "already_running", "message": "JMS listener is already running"}

    _jms_listener_engine.start()
    return {"status": "started", "message": "JMS listener started"}


@router.post("/jms/listener/stop", tags=["JMS"])
async def stop_listener():
    """
    Stop the JMS listener engine.

    Messages will accumulate on the broker queues while the listener is
    stopped and will be processed when it is restarted.
    """
    if _jms_listener_engine is None:
        raise HTTPException(status_code=503, detail="JMS listener not initialised")

    if not _jms_listener_engine.is_running():
        return {"status": "already_stopped", "message": "JMS listener is already stopped"}

    _jms_listener_engine.stop()
    return {"status": "stopped", "message": "JMS listener stopped"}


# ---------------------------------------------------------------------------
# Per-queue endpoints
# ---------------------------------------------------------------------------

@router.get("/jms/queues", tags=["JMS"])
async def get_queue_statuses():
    """
    List all JMS queues that the listener knows about, with their
    enabled / paused state.
    """
    if _jms_listener_engine is None:
        return {"queues": [], "note": "JMS listener not initialised"}

    status_map = _jms_listener_engine.get_queue_status()
    return {
        "queues": list(status_map.values()),
        "total": len(status_map)
    }


@router.post("/jms/queues/{queue_name}/pause", tags=["JMS"])
async def pause_queue(queue_name: str):
    """
    Pause listening on a specific JMS queue.

    The listener thread continues running and other queues are unaffected.
    Messages sent to this queue while it is paused remain on the broker
    and will be processed once the queue is resumed — **no messages are lost**.
    """
    if _jms_listener_engine is None:
        raise HTTPException(status_code=503, detail="JMS listener not initialised")

    _jms_listener_engine.pause_queue(queue_name)
    return {
        "status": "paused",
        "queue": queue_name,
        "message": f"Queue '{queue_name}' paused — messages will accumulate on the broker"
    }


@router.post("/jms/queues/{queue_name}/resume", tags=["JMS"])
async def resume_queue(queue_name: str):
    """
    Resume listening on a previously paused JMS queue.

    Any messages that accumulated while the queue was paused will be
    processed as soon as the next poll cycle runs.
    """
    if _jms_listener_engine is None:
        raise HTTPException(status_code=503, detail="JMS listener not initialised")

    was_paused = _jms_listener_engine.resume_queue(queue_name)
    if not was_paused:
        return {
            "status": "not_paused",
            "queue": queue_name,
            "message": f"Queue '{queue_name}' was not paused"
        }
    return {
        "status": "resumed",
        "queue": queue_name,
        "message": f"Queue '{queue_name}' resumed"
    }

