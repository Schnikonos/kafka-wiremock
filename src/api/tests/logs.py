"""
Test log file retrieval endpoints.
"""
import logging
import os
from typing import Dict, Any, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"])


@router.get("/logs")
async def list_test_logs() -> Dict[str, Any]:
    """
    List all test log files.

    Returns:
        Dictionary with log files and their content
    """
    try:
        test_suite_dir = Path(os.getenv("TEST_SUITE_DIR", "/testSuite"))

        # Find all .test.log files recursively
        log_files = sorted(test_suite_dir.rglob("*.test.log"))

        if not log_files:
            return {
                "total": 0,
                "logs": [],
                "test_suite_dir": str(test_suite_dir),
                "test_suite_exists": test_suite_dir.exists()
            }

        logs = []
        for log_file in log_files:
            try:
                with open(log_file, 'r') as f:
                    content = f.read()
                logs.append({
                    "path": str(log_file),
                    "relative_path": str(log_file.relative_to(test_suite_dir)),
                    "size_bytes": log_file.stat().st_size,
                    "modified": log_file.stat().st_mtime,
                    "content_preview": content[:500] + ("..." if len(content) > 500 else "")
                })
            except Exception as e:
                logger.error(f"Failed to read log file {log_file}: {e}")
                logs.append({
                    "path": str(log_file),
                    "error": str(e)
                })

        return {
            "total": len(logs),
            "logs": logs,
            "test_suite_dir": str(test_suite_dir)
        }
    except Exception as e:
        logger.error(f"Error listing test logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/{test_id}")
async def get_test_log(test_id: str) -> Dict[str, Any]:
    """
    Get the log file content for a specific test.

    Args:
        test_id: Test identifier (uses the test name to find the log)

    Returns:
        Full log file content
    """
    try:
        test_suite_dir = Path(os.getenv("TEST_SUITE_DIR", "/testSuite"))

        # Search for log file matching the test ID
        log_files = list(test_suite_dir.rglob("*.test.log"))

        matching_logs = [
            lf for lf in log_files
            if test_id in lf.name or test_id in lf.read_text()
        ]

        if not matching_logs:
            raise HTTPException(
                status_code=404,
                detail=f"No log file found for test '{test_id}'"
            )

        log_file = matching_logs[0]

        with open(log_file, 'r') as f:
            content = f.read()

        return {
            "test_id": test_id,
            "log_path": str(log_file),
            "log_size_bytes": log_file.stat().st_size,
            "content": content
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving log for test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

