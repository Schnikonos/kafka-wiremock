"""
Job manager for async test execution.
Tracks test run status and results for polling-based execution.
"""
import logging
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job execution status."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class TestRunJob:
    """Represents an async test execution job."""
    job_id: str
    test_id: str
    status: JobStatus = JobStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    errors: list = field(default_factory=list)
    progress_pct: int = 0  # 0-100

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "job_id": self.job_id,
            "test_id": self.test_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "errors": self.errors,
            "progress_pct": self.progress_pct
        }


class TestJobManager:
    """Manages async test execution jobs."""

    def __init__(self):
        """Initialize job manager."""
        self.jobs: Dict[str, TestRunJob] = {}

    def create_job(self, test_id: str) -> str:
        """
        Create a new test run job.

        Args:
            test_id: Test identifier

        Returns:
            job_id for tracking
        """
        job_id = str(uuid.uuid4())
        job = TestRunJob(job_id=job_id, test_id=test_id)
        self.jobs[job_id] = job
        logger.info(f"Created job {job_id} for test {test_id}")
        return job_id

    def get_job(self, job_id: str) -> Optional[TestRunJob]:
        """Get job by ID."""
        return self.jobs.get(job_id)

    def start_job(self, job_id: str):
        """Mark job as started."""
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow().isoformat() + "Z"
            logger.info(f"Job {job_id} started")

    def update_progress(self, job_id: str, progress_pct: int):
        """Update job progress."""
        job = self.get_job(job_id)
        if job:
            job.progress_pct = min(100, max(0, progress_pct))

    def complete_job(self, job_id: str, result: Dict[str, Any]):
        """Mark job as completed with result."""
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow().isoformat() + "Z"
            job.result = result
            job.progress_pct = 100
            logger.info(f"Job {job_id} completed")

    def fail_job(self, job_id: str, error: str):
        """Mark job as failed."""
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.utcnow().isoformat() + "Z"
            job.errors.append(error)
            logger.error(f"Job {job_id} failed: {error}")

    def cancel_job(self, job_id: str):
        """Cancel a job."""
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.utcnow().isoformat() + "Z"
            logger.info(f"Job {job_id} cancelled")

    def cleanup_completed_job(self, job_id: str) -> bool:
        """
        Remove completed job from memory.

        Args:
            job_id: Job ID to cleanup

        Returns:
            True if job was cleaned up, False if not found or still running
        """
        job = self.get_job(job_id)
        if not job:
            return False

        if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            del self.jobs[job_id]
            logger.info(f"Job {job_id} cleaned up from memory")
            return True

        logger.warning(f"Cannot cleanup job {job_id}: status is {job.status}")
        return False

    def list_jobs(self, test_id: Optional[str] = None) -> list:
        """List all jobs, optionally filtered by test ID."""
        jobs = list(self.jobs.values())
        if test_id:
            jobs = [j for j in jobs if j.test_id == test_id]
        return [j.to_dict() for j in jobs]

