"""
Bulk test execution endpoints for running multiple tests with repeat functionality.
"""
import logging
import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"])

# Global references - will be set by main.py
_test_loader = None
_test_suite_runner = None
_results_db = None


def set_test_loader(loader):
    """Set the global test loader reference."""
    global _test_loader
    _test_loader = loader


def set_test_suite_runner(runner):
    """Set the global test suite runner reference."""
    global _test_suite_runner
    _test_suite_runner = runner


def set_results_db(db):
    """Set the global results database reference."""
    global _results_db
    _results_db = db


class BulkTestRequest(BaseModel):
    """Request to run multiple tests."""
    test_ids: List[str]  # Test identifiers to run
    mode: str = "parallel"  # "parallel" or "sequential"
    repeat: int = 1  # Number of times to run each test
    parallel_workers: int = 4  # Workers for parallel execution
    repeat_mode: str = "interleaved-repeats"  # "interleaved-repeats" or "sequential-repeats"
    force_run: bool = False  # Run even if test.skip == True (explicit selection)


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


@router.post(":bulk")
async def run_tests_bulk(request: BulkTestRequest) -> Dict[str, Any]:
    """
    Run multiple tests in bulk with repeat and parallelism options.

    Args:
        request: BulkTestRequest with test_ids, mode, repeat, parallel_workers, repeat_mode

    Returns:
        Aggregated results for all test executions
    """
    if not _test_loader or not _test_suite_runner:
        raise HTTPException(status_code=503, detail="Test suite not initialized")

    try:
        # Validate test IDs
        all_tests = _test_loader.discover_tests()
        selected_tests = []
        for test_id in request.test_ids:
            test = next((t for t in all_tests if t.name == test_id), None)
            if not test:
                raise HTTPException(status_code=404, detail=f"Test not found: {test_id}")
            selected_tests.append(test)

        # Create a list of tests to run based on repeat count
        tests_to_run = []
        for _ in range(request.repeat):
            tests_to_run.extend(selected_tests)

        logger.info(
            f"Running {len(selected_tests)} tests, {request.repeat} times each "
            f"({len(tests_to_run)} total) in {request.mode} mode"
        )

        # Read verbose_tests flag from app settings.
        # Import the MODULE (not a variable copy) so we always get the live object.
        # Use getattr() for backward-compat in case the attribute doesn't exist yet
        # on an old in-memory settings instance (avoids silent AttributeError).
        verbose = False
        try:
            from ...api import app_settings as _app_settings_mod
            _asl = _app_settings_mod.app_settings_loader
            if _asl:
                verbose = bool(getattr(_asl.get_settings().ui, 'verbose_tests', False))
        except Exception as _ve:
            logger.debug(f"Could not read verbose_tests from app settings: {_ve}")

        # Execute tests
        if request.mode == "parallel":
            # Use asyncio.gather for true concurrent async execution
            results = await asyncio.gather(
                *[_test_suite_runner.executor.run_test(
                    test,
                    Path(test.file_path) if test.file_path else None,
                    verbose=verbose,
                    force_run=request.force_run
                  )
                  for test in tests_to_run],
                return_exceptions=False
            )
        else:  # sequential
            results = []
            for test in tests_to_run:
                r = await _test_suite_runner.executor.run_test(
                    test,
                    Path(test.file_path) if test.file_path else None,
                    verbose=verbose,
                    force_run=request.force_run
                )
                results.append(r)
                logger.info(f"Test {test.name}: {r.status}")

        # Aggregate results
        passed_count = sum(1 for r in results if r.status == "PASSED")
        failed_count = sum(1 for r in results if r.status == "FAILED")
        skipped_count = sum(1 for r in results if r.status == "SKIPPED")

        aggregated = {
            "total": len(results),
            "passed": passed_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "mode": request.mode,
            "repeat": request.repeat,
            "parallel_workers": request.parallel_workers,
            "repeat_mode": request.repeat_mode,
            "elapsed_ms": sum(r.elapsed_ms for r in results),
            "results": [_convert_test_result_to_dict(r) for r in results]
        }

        # Save to results database if available
        if _results_db:
            try:
                from ...test.results_db import ExecutionResult
                result_record = ExecutionResult(
                    type='test',
                    execution_ids=request.test_ids,
                    mode=request.mode,
                    repeat=request.repeat,
                    repeat_mode=request.repeat_mode,
                    parallel_workers=request.parallel_workers,
                    total=len(results),
                    passed=passed_count,
                    failed=failed_count,
                    skipped=skipped_count,
                    elapsed_ms=sum(r.elapsed_ms for r in results),
                    results=json.dumps(aggregated['results']),
                    status='SUCCESS' if failed_count == 0 else 'PARTIAL'
                )
                saved_result = _results_db.save_result(result_record)
                aggregated['result_id'] = saved_result.id
                logger.info(f"Saved test results to database: {saved_result.id}")
            except Exception as e:
                logger.error(f"Failed to save results to database: {e}")
                # Continue anyway, database save is optional

        return aggregated

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk test execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

