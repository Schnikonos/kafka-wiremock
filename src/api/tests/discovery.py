"""
Test discovery and definition endpoints.
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from ...test.loader import TestInjection, TestExpectation, TestScript

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"])

# Global reference - will be set by main.py
_test_loader = None


def set_test_loader(loader):
    """Set the global test loader reference."""
    global _test_loader
    _test_loader = loader


@router.get("")
async def list_tests(errors: bool = Query(False, description="If true, include validation errors")) -> Dict[str, Any]:
    """
    List all discovered test definitions.

    Args:
        errors: If true, include validation errors for all test files

    Returns:
        Dictionary with test metadata, optionally including validation errors
    """
    if not _test_loader:
        raise HTTPException(status_code=503, detail="Test loader not initialized")

    try:
        tests = _test_loader.discover_tests()
        result = []
        for test in tests:
            when_injections = sum(1 for item in test.when.items if isinstance(item, TestInjection))
            then_expectations = sum(1 for item in test.then.items if isinstance(item, TestExpectation))
            result.append({
                "test_id": test.name,
                "priority": test.priority,
                "tags": test.tags,
                "skip": test.skip,
                "timeout_ms": test.timeout_ms,
                "when_injections": when_injections,
                "then_expectations": then_expectations
            })

        response = {
            "total": len(result),
            "tests": result
        }

        # Add validation errors if requested
        if errors:
            response["validation_errors"] = _test_loader.validation_errors or {}
            response["has_errors"] = bool(_test_loader.validation_errors)

        return response
    except Exception as e:
        logger.error(f"Error listing tests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{test_id}")
async def get_test_definition(test_id: str) -> Dict[str, Any]:
    """
    Get parsed test definition.
    Args:
        test_id: Test identifier (from test name)
    Returns:
        Test definition as dictionary
    """
    if not _test_loader:
        raise HTTPException(status_code=503, detail="Test loader not initialized")

    try:
        tests = _test_loader.discover_tests()
        test = next((t for t in tests if t.name == test_id), None)
        if not test:
            raise HTTPException(status_code=404, detail=f"Test not found: {test_id}")

        return {
            "name": test.name,
            "priority": test.priority,
            "tags": test.tags,
            "skip": test.skip,
            "timeout_ms": test.timeout_ms,
            "when": {
                "injections": [
                    {
                        "message_id": inj.message_id,
                        "topic": inj.topic,
                        "delay_ms": inj.delay_ms
                    }
                    for inj in test.when.items if isinstance(inj, TestInjection)
                ],
                "has_script": any(isinstance(item, TestScript) for item in test.when.items)
            },
            "then": {
                "expectations": [
                    {
                        "topic": exp.topic,
                        "source_id": exp.source_id,
                        "target_id": exp.target_id,
                        "wait_ms": exp.wait_ms,
                        "conditions_count": len(exp.match)
                    }
                    for exp in test.then.items if isinstance(exp, TestExpectation)
                ],
                "has_script": any(isinstance(item, TestScript) for item in test.then.items)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))



