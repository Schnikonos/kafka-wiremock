"""
Asynchronous test job management endpoints.
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"])

# Global reference - will be set by main.py
_test_job_manager = None


def set_test_job_manager(manager):
    """Set the global test job manager reference."""
    global _test_job_manager
    _test_job_manager = manager


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get status of an async test job.

    Args:
        job_id: Job ID returned from async test POST

    Returns:
        Job status, progress, and result if completed
    """
    if not _test_job_manager:
        raise HTTPException(status_code=503, detail="Job manager not initialized")

    try:
        job = _test_job_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

        response = job.to_dict()

        # If job is complete, clean it up on next access
        if job.status.value in ["COMPLETED", "FAILED", "CANCELLED"]:
            # Mark for cleanup but return the result first
            pass

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs")
async def list_jobs(test_id: Optional[str] = Query(None, description="Filter by test ID")) -> Dict[str, Any]:
    """
    List all running/completed jobs.

    Args:
        test_id: Optional test ID to filter by

    Returns:
        List of jobs with their status
    """
    if not _test_job_manager:
        raise HTTPException(status_code=503, detail="Job manager not initialized")

    try:
        jobs = _test_job_manager.list_jobs(test_id)
        return {
            "total": len(jobs),
            "jobs": jobs
        }
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

