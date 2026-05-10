"""
Bulk send execution endpoints for running multiple sends with repeat functionality.
"""
import logging
import asyncio
import json
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/send", tags=["send"])

# Global references - will be set by main.py
_send_loader = None
_send_executor = None
_results_db = None


def set_send_loader(loader):
    """Set the global send loader reference."""
    global _send_loader
    _send_loader = loader


def set_send_executor(executor):
    """Set the global send executor reference."""
    global _send_executor
    _send_executor = executor


def set_results_db(db):
    """Set the global results database reference."""
    global _results_db
    _results_db = db


class BulkSendRequest(BaseModel):
    """Request to run multiple sends."""
    send_ids: List[str]  # Send identifiers to run
    mode: str = "sequential"  # "parallel" or "sequential"
    repeat: int = 1  # Number of times to run each send
    parallel_workers: int = 4  # Workers for parallel execution (ignored if mode is sequential)
    repeat_mode: str = "interleaved-repeats"  # "interleaved-repeats" or "sequential-repeats"


def _convert_send_result_to_dict(result) -> Dict[str, Any]:
    """Convert a SendResult object to a JSON-serializable dictionary."""
    return {
        "send_id": result.send_id,
        "status": result.status,
        "elapsed_ms": result.elapsed_ms,
        "injected": result.injected,
        "errors": result.errors
    }


@router.post(":bulk")
async def run_sends_bulk(request: BulkSendRequest) -> Dict[str, Any]:
    """
    Run multiple sends in bulk with repeat option.

    Args:
        request: BulkSendRequest with send_ids, mode, repeat, parallel_workers, repeat_mode

    Returns:
        Aggregated results for all send executions
    """
    if not _send_loader or not _send_executor:
        raise HTTPException(status_code=503, detail="Send executor not initialized")

    try:
        # Validate send IDs
        all_sends = _send_loader.discover_sends()
        selected_sends = []
        for send_id in request.send_ids:
            send = next((s for s in all_sends if s.name == send_id), None)
            if not send:
                raise HTTPException(status_code=404, detail=f"Send not found: {send_id}")
            selected_sends.append(send)

        logger.info(
            f"Running {len(selected_sends)} sends, {request.repeat} times each "
            f"({len(selected_sends) * request.repeat} total) in {request.mode} mode"
        )

        # Execute sends
        results = []
        for iteration in range(request.repeat):
            if request.mode == "parallel":
                # Run all sends concurrently (limit workers based on parallel_workers)
                # For sends, we'll use asyncio gather with semaphore to limit concurrency
                semaphore = asyncio.Semaphore(request.parallel_workers)

                async def run_with_semaphore(send):
                    async with semaphore:
                        return await _send_executor.run_send(send)

                send_results = await asyncio.gather(
                    *[run_with_semaphore(send) for send in selected_sends]
                )
                results.extend(send_results)
            else:  # sequential
                # Run sends one by one
                for send in selected_sends:
                    result = await _send_executor.run_send(send)
                    results.append(result)

        # Aggregate results
        completed_count = sum(1 for r in results if r.status == "COMPLETED")
        failed_count = sum(1 for r in results if r.status == "FAILED")
        skipped_count = sum(1 for r in results if r.status == "SKIPPED")

        aggregated = {
            "total": len(results),
            "completed": completed_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "mode": request.mode,
            "repeat": request.repeat,
            "parallel_workers": request.parallel_workers,
            "repeat_mode": request.repeat_mode,
            "elapsed_ms": sum(r.elapsed_ms for r in results),
            "results": [_convert_send_result_to_dict(r) for r in results]
        }

        # Save to results database if available
        if _results_db:
            try:
                from ...test.results_db import ExecutionResult
                result_record = ExecutionResult(
                    type='send',
                    execution_ids=request.send_ids,
                    mode=request.mode,
                    repeat=request.repeat,
                    repeat_mode=request.repeat_mode,
                    parallel_workers=request.parallel_workers,
                    total=len(results),
                    completed=completed_count,
                    failed=failed_count,
                    skipped=skipped_count,
                    elapsed_ms=sum(r.elapsed_ms for r in results),
                    results=json.dumps(aggregated['results']),
                    status='SUCCESS' if failed_count == 0 else 'PARTIAL'
                )
                saved_result = _results_db.save_result(result_record)
                aggregated['result_id'] = saved_result.id
                logger.info(f"Saved send results to database: {saved_result.id}")
            except Exception as e:
                logger.error(f"Failed to save results to database: {e}")
                # Continue anyway, database save is optional

        return aggregated

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk send execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

