"""
Test execution endpoints.
"""
import logging
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"])

# Global references - will be set by main.py
_test_loader = None
_test_suite_runner = None
_test_job_manager = None


def set_test_loader(loader):
    """Set the global test loader reference."""
    global _test_loader
    _test_loader = loader


def set_test_suite_runner(runner):
    """Set the global test suite runner reference."""
    global _test_suite_runner
    _test_suite_runner = runner


def set_test_job_manager(manager):
    """Set the global test job manager reference."""
    global _test_job_manager
    _test_job_manager = manager


def _convert_test_result_to_dict(result) -> Dict[str, Any]:
    """Convert a TestResult object to a JSON-serializable dictionary."""
    return {
        "test_id": result.test_id,
        "status": result.status,
        "elapsed_ms": result.elapsed_ms,
        "when_result": {
            "injected": result.when_result.injected,
            "script_error": result.when_result.script_error
        },
        "then_result": {
            "expectations": [
                {
                    "index": exp.index,
                    "topic": exp.topic,
                    "expected": exp.expected,
                    "received": exp.received,
                    "status": exp.status,
                    "elapsed_ms": exp.elapsed_ms,
                    "error": exp.error
                }
                for exp in result.then_result.expectations
            ],
            "script_error": result.then_result.script_error
        },
        "errors": result.errors
    }


@router.post("/{test_id}")
async def run_single_test(
    test_id: str,
    async_mode: bool = Query(False, description="If true, run asynchronously and return job_id"),
    verbose: bool = Query(False, description="If true, include received_messages and skipped_messages in logs")
) -> Dict[str, Any]:
    """
    Run a single test by ID.

    Args:
        test_id: Test identifier
        async_mode: If true, returns immediately with job_id (202 Accepted)
        verbose: If true, include detailed message logs in test output

    Returns:
        If async_mode: {job_id, status, created_at}
        If sync_mode: Full test result
    """
    if not _test_loader or not _test_suite_runner or not _test_job_manager:
        raise HTTPException(status_code=503, detail="Test suite not initialized")

    try:
        tests = _test_loader.discover_tests()
        test = next((t for t in tests if t.name == test_id), None)
        if not test:
            raise HTTPException(status_code=404, detail=f"Test not found: {test_id}")

        if async_mode:
            # Create async job
            job_id = _test_job_manager.create_job(test_id)
            _test_job_manager.start_job(job_id)

            # Run test in background
            asyncio.create_task(
                _run_test_async(job_id, test, verbose)
            )

            # Return 202 Accepted with job info
            return {
                "job_id": job_id,
                "status": "RUNNING",
                "created_at": _test_job_manager.get_job(job_id).created_at,
                "message": "Test running asynchronously. Use GET /tests/jobs/{job_id} to poll status."
            }
        else:
            # Synchronous execution (current behavior)
            # Use file_path stored in test definition
            test_file_path = Path(test.file_path) if test.file_path else None

            result = await _test_suite_runner.executor.run_test(test, test_file_path, verbose=verbose)

            # Convert result to JSON-serializable dict
            return _convert_test_result_to_dict(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _run_test_async(job_id: str, test, verbose: bool = False):
    """Helper to run test asynchronously and update job status."""
    try:
        # Use file_path stored in test definition
        test_file_path = Path(test.file_path) if test.file_path else None

        result = await _test_suite_runner.executor.run_test(test, test_file_path, verbose=verbose)

        # Convert to dict
        result_dict = _convert_test_result_to_dict(result)

        _test_job_manager.complete_job(job_id, result_dict)
    except Exception as e:
        logger.error(f"Async test {job_id} failed: {e}")
        _test_job_manager.fail_job(job_id, str(e))


@router.post(":bulk")
async def run_tests_bulk(
    mode: str = Query("parallel", description="sequential or parallel"),
    threads: int = Query(4, ge=1, le=32, description="Number of concurrent threads (for parallel mode)"),
    iterations: int = Query(1, ge=1, le=1000, description="Number of iterations per test"),
    filter_tags: Optional[list] = Query(None, description="Optional tags to filter tests"),
    verbose: bool = Query(False, description="If true, include received_messages and skipped_messages in logs")
) -> Dict[str, Any]:
    """
    Run all discovered tests in bulk.
    Args:
        mode: Execution mode (sequential or parallel)
        threads: Number of concurrent threads
        iterations: Number of iterations per test
        filter_tags: Optional tags to filter tests
        verbose: If true, include detailed message logs in test output
    Returns:
        Aggregated test results
    """
    if not _test_loader or not _test_suite_runner:
        raise HTTPException(status_code=503, detail="Test suite not initialized")

    try:
        if mode not in ["sequential", "parallel"]:
            raise HTTPException(status_code=400, detail="mode must be 'sequential' or 'parallel'")

        # Discover tests
        all_tests = _test_loader.discover_tests()

        # Filter by tags if specified
        if filter_tags:
            all_tests = _test_loader.get_tests_by_tag(all_tests, filter_tags)

        if not all_tests:
            raise HTTPException(status_code=400, detail="No tests found matching criteria")

        # Replicate tests for iterations
        tests_to_run = all_tests * iterations

        logger.info(f"Running {len(tests_to_run)} test instances ({len(all_tests)} tests × {iterations} iterations) in {mode} mode (verbose={verbose})")

        # Run tests
        if mode == "sequential":
            results = await _test_suite_runner.run_tests_sequential(tests_to_run, verbose=verbose)
        else:  # parallel
            results = await _test_suite_runner.run_tests_parallel(tests_to_run, threads=threads, verbose=verbose)

        # Aggregate results
        from ...test.suite import TestResultAggregator
        aggregated = TestResultAggregator.aggregate_results(results, mode=mode)

        return aggregated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running bulk tests: {e}")
        raise HTTPException(status_code=500, detail=str(e))

