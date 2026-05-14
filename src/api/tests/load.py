"""
Load testing API endpoints — Gatling-style closed-model scenarios.

Routes (all under /api prefix from main.py):
  POST   /tests/load                  Start a new load scenario
  GET    /tests/load/{job_id}         Poll progress + partial metrics
  GET    /tests/load/{job_id}/report  Fetch final report
  DELETE /tests/load/{job_id}         Cancel a running job
  GET    /tests/load                  List all load jobs
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/load-tests", tags=["load-testing"])

# ---------------------------------------------------------------------------
# Global state set by main.py
# ---------------------------------------------------------------------------
_test_loader = None
_test_suite_runner = None


def set_test_loader(loader):
    global _test_loader
    _test_loader = loader


def set_test_suite_runner(runner):
    global _test_suite_runner
    _test_suite_runner = runner


# In-memory job registry  {job_id: dict}
_load_jobs: Dict[str, Dict[str, Any]] = {}
# asyncio Task handles for cancellation  {job_id: Task}
_load_tasks: Dict[str, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class LoadPhaseRequest(BaseModel):
    type: str = "steady"        # "ramp" | "steady"
    duration_s: int = 30
    from_users: int = 0
    to_users: int = 1
    model: str = "closed"


class LoadScenarioRequest(BaseModel):
    name: str = "load-scenario"
    test_ids: List[str]
    phases: List[LoadPhaseRequest]
    think_time_ms: int = 0
    bucket_s: int = Field(default=5, ge=1, le=60)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("")
async def start_load_test(request: LoadScenarioRequest) -> Dict[str, Any]:
    """
    Start a Gatling-style load scenario.

    Returns a job_id to track progress via GET /tests/load/{job_id}.
    """
    if not _test_loader or not _test_suite_runner:
        raise HTTPException(status_code=503, detail="Test suite not initialized")

    # Import here to avoid circular imports at module level
    from ...test.load_scenario import LoadPhase, LoadScenario
    from ...test.load_runner import LoadRunner

    try:
        phases = [
            LoadPhase(
                type=p.type,
                duration_s=p.duration_s,
                from_users=p.from_users,
                to_users=p.to_users,
                model=p.model,
            )
            for p in request.phases
        ]
        scenario = LoadScenario(
            name=request.name,
            test_ids=request.test_ids,
            phases=phases,
            think_time_ms=request.think_time_ms,
            bucket_s=request.bucket_s,
        )
        scenario.validate()
    except (ValueError, NotImplementedError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    job_id = str(uuid.uuid4())
    _load_jobs[job_id] = {
        "job_id": job_id,
        "scenario_name": scenario.name,
        "scenario": scenario.to_dict(),
        "status": "PENDING",
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
        "started_at": None,
        "active_users": 0,
        "progress_pct": 0,
        "elapsed_s": 0,
        "buckets": [],
        "report": None,
        "error": None,
    }

    runner = LoadRunner(
        test_executor=_test_suite_runner.executor,
        test_loader=_test_loader,
    )

    async def _run_and_store():
        try:
            await runner.run(scenario, job_id, _load_jobs)
        except Exception as exc:
            logger.error(f"Load job {job_id} failed: {exc}", exc_info=True)
            _load_jobs[job_id]["status"] = "FAILED"
            _load_jobs[job_id]["error"] = str(exc)
        finally:
            _load_tasks.pop(job_id, None)

    task = asyncio.create_task(_run_and_store())
    _load_tasks[job_id] = task

    logger.info(
        f"Started load job {job_id}: scenario='{scenario.name}' "
        f"tests={scenario.test_ids} duration={scenario.total_duration_s()}s"
    )
    return {
        "job_id": job_id,
        "scenario_name": scenario.name,
        "total_duration_s": scenario.total_duration_s(),
        "status": "PENDING",
    }


@router.get("")
async def list_load_jobs() -> Dict[str, Any]:
    """List all load jobs (active and completed)."""
    jobs = []
    for job in _load_jobs.values():
        jobs.append({
            "job_id": job["job_id"],
            "scenario_name": job.get("scenario_name", ""),
            "status": job.get("status", "UNKNOWN"),
            "created_at": job.get("created_at"),
            "progress_pct": job.get("progress_pct", 0),
            "elapsed_s": job.get("elapsed_s", 0),
        })
    # Most recent first
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return {"total": len(jobs), "jobs": jobs}


@router.get("/{job_id}")
async def get_load_job(job_id: str) -> Dict[str, Any]:
    """
    Poll a running load job.

    Returns current status, progress, active user count, and all flushed
    metric buckets so far (for live chart rendering).
    """
    job = _load_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Load job not found: {job_id}")

    # While running, refresh buckets from the live collector
    collector = job.get("collector")
    if collector and job.get("status") == "RUNNING":
        job["buckets"] = collector.get_flushed_dicts()

    return {
        "job_id": job_id,
        "scenario_name": job.get("scenario_name"),
        "scenario": job.get("scenario"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "active_users": job.get("active_users", 0),
        "progress_pct": job.get("progress_pct", 0),
        "elapsed_s": job.get("elapsed_s", 0),
        "buckets": job.get("buckets", []),
        "error": job.get("error"),
    }


@router.get("/{job_id}/report")
async def get_load_report(job_id: str) -> Dict[str, Any]:
    """
    Fetch the final report for a completed load job.

    Returns full time-series buckets and per-test summary statistics
    suitable for rendering a Gatling-style HTML report in the UI.
    """
    job = _load_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Load job not found: {job_id}")

    status = job.get("status", "UNKNOWN")
    if status in ("PENDING", "RUNNING"):
        raise HTTPException(
            status_code=202,
            detail=f"Load job is still {status}. Poll GET /tests/load/{job_id} for progress.",
        )

    report = job.get("report")
    if not report:
        raise HTTPException(
            status_code=500,
            detail="Report data not available (job may have failed before completion).",
        )

    return report


@router.delete("/{job_id}")
async def cancel_load_job(job_id: str) -> Dict[str, Any]:
    """Cancel a running load job."""
    job = _load_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Load job not found: {job_id}")

    task = _load_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
        logger.info(f"Cancelled load job {job_id}")
        return {"job_id": job_id, "status": "CANCELLING"}

    return {"job_id": job_id, "status": job.get("status", "UNKNOWN")}







