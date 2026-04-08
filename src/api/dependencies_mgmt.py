"""
Python dependency management endpoints.
"""
import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["dependencies"])

# Global reference - will be set by main.py
_dependency_manager = None


def set_dependency_manager(manager):
    """Set the global dependency manager reference."""
    global _dependency_manager
    _dependency_manager = manager


@router.get("/dependencies")
async def get_dependency_status() -> Dict[str, Any]:
    """
    Get status of Python dependency manager.

    Returns:
        Dependency status, requirements.txt existence, and last installation info
    """
    if not _dependency_manager:
        raise HTTPException(status_code=503, detail="Dependency manager not initialized")

    try:
        requirements_exists = _dependency_manager.requirements_file.exists()
        log_exists = _dependency_manager.log_file.exists()

        result = {
            "status": "running" if _dependency_manager._running else "stopped",
            "requirements_file": str(_dependency_manager.requirements_file),
            "requirements_exists": requirements_exists,
            "log_file": str(_dependency_manager.log_file),
            "log_exists": log_exists,
            "scan_interval_seconds": _dependency_manager.scan_interval
        }

        # Include last few lines of log if it exists
        if log_exists:
            try:
                with open(_dependency_manager.log_file, 'r') as f:
                    log_content = f.read()
                    result["last_installation_log"] = log_content
            except Exception as e:
                logger.warning(f"Failed to read dependency log: {e}")

        return result
    except Exception as e:
        logger.error(f"Error retrieving dependency status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

