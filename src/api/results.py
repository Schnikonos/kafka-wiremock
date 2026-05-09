"""
API endpoints for managing execution results from the database.
"""
import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/results", tags=["results"])

# Global reference - will be set by main.py
_results_db = None


def set_results_db(db):
    """Set the global results database reference."""
    global _results_db
    _results_db = db


class ResultSummary(BaseModel):
    """Summary of stored execution result."""
    id: str
    type: str
    execution_ids: List[str]
    mode: str
    repeat: int
    total: int
    failed: int
    skipped: int
    elapsed_ms: int
    created_at: str
    status: str


class ResultStatistics(BaseModel):
    """Statistics for execution results."""
    total_executions: int
    total_items: int
    total_passed: int
    total_failed: int
    total_completed: int
    total_skipped: int
    total_time_ms: int
    avg_time_ms: int


@router.get("/list")
async def list_results(
    type: Optional[str] = Query(None, description="Filter by type: 'test', 'send', or None for all"),
    limit: int = Query(50, ge=1, le=500, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
) -> Dict[str, Any]:
    """
    List execution results with pagination.

    Args:
        type: Optional filter by 'test' or 'send'
        limit: Number of results per page
        offset: Pagination offset

    Returns:
        Dictionary with results and metadata
    """
    if not _results_db:
        raise HTTPException(status_code=503, detail="Results database not initialized")

    try:
        results = _results_db.list_results(result_type=type, limit=limit, offset=offset)
        total = _results_db.count_results(result_type=type)

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "count": len(results),
            "results": [
                {
                    "id": r.id,
                    "type": r.type,
                    "execution_ids": r.execution_ids,
                    "mode": r.mode,
                    "repeat": r.repeat,
                    "total": r.total,
                    "failed": r.failed,
                    "completed": r.completed,
                    "skipped": r.skipped,
                    "elapsed_ms": r.elapsed_ms,
                    "created_at": r.created_at,
                    "status": r.status
                }
                for r in results
            ]
        }
    except Exception as e:
        logger.error(f"Error listing results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{result_id}")
async def get_result(result_id: str) -> Dict[str, Any]:
    """
    Get detailed execution result by ID.

    Args:
        result_id: Result identifier

    Returns:
        Complete execution result with detailed results
    """
    if not _results_db:
        raise HTTPException(status_code=503, detail="Results database not initialized")

    try:
        result = _results_db.get_result(result_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Result not found: {result_id}")

        return {
            "id": result.id,
            "type": result.type,
            "execution_ids": result.execution_ids,
            "mode": result.mode,
            "repeat": result.repeat,
            "repeat_mode": result.repeat_mode,
            "parallel_workers": result.parallel_workers,
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "completed": result.completed,
            "skipped": result.skipped,
            "elapsed_ms": result.elapsed_ms,
            "status": result.status,
            "error_message": result.error_message,
            "created_at": result.created_at,
            "updated_at": result.updated_at,
            "results": result.results  # JSON string of individual results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving result {result_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{result_id}")
async def delete_result(result_id: str) -> Dict[str, str]:
    """
    Delete execution result by ID.

    Args:
        result_id: Result identifier

    Returns:
        Confirmation message
    """
    if not _results_db:
        raise HTTPException(status_code=503, detail="Results database not initialized")

    try:
        deleted = _results_db.delete_result(result_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Result not found: {result_id}")

        logger.info(f"Deleted execution result: {result_id}")
        return {"message": f"Result {result_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting result {result_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup")
async def cleanup_old_results(days: int = Query(30, ge=1, le=365, description="Keep results from last N days")) -> Dict[str, Any]:
    """
    Delete execution results older than specified number of days.

    Args:
        days: Keep results from last N days (1-365)

    Returns:
        Information about deleted results
    """
    if not _results_db:
        raise HTTPException(status_code=503, detail="Results database not initialized")

    try:
        deleted = _results_db.delete_old_results(days=days)
        logger.info(f"Cleanup: deleted {deleted} results older than {days} days")

        return {
            "status": "success",
            "message": f"Deleted {deleted} results older than {days} days",
            "deleted_count": deleted
        }
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/summary")
async def get_statistics(
    type: Optional[str] = Query(None, description="Filter by type: 'test' or 'send'"),
    days: int = Query(30, ge=1, le=365, description="Statistics for last N days")
) -> Dict[str, Any]:
    """
    Get execution statistics.

    Args:
        type: Optional filter by 'test' or 'send'
        days: Statistics for last N days

    Returns:
        Statistics summary
    """
    if not _results_db:
        raise HTTPException(status_code=503, detail="Results database not initialized")

    try:
        stats = _results_db.get_statistics(result_type=type, days=days)
        return {
            "period_days": days,
            "filter_type": type or "all",
            **stats
        }
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

