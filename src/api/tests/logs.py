"""
Test log file retrieval endpoints.
Log files use JSON-Lines format (one JSON object per line = one run).
Up to MAX_RUNS_PER_FILE runs are kept per file.
"""
import logging
import os
import json
import re
from typing import Dict, Any, Optional, List
from pathlib import Path
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"])


def _parse_log_file(path: Path) -> List[Dict[str, Any]]:
    """Return a list of run-dicts from a JSON-Lines log file (newest first)."""
    runs: List[Dict[str, Any]] = []
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    # Legacy YAML-like format: try to extract status/elapsed with regex
                    status_m = re.search(r'^status:\s*"?([A-Z_]+)"?', line, re.MULTILINE)
                    elapsed_m = re.search(r'^elapsed_ms:\s*(\d+)', line, re.MULTILINE)
                    runs.append({
                        "status": status_m.group(1) if status_m else "UNKNOWN",
                        "elapsed_ms": int(elapsed_m.group(1)) if elapsed_m else 0,
                        "raw": line,
                    })
    except Exception as e:
        logger.error(f"Failed to parse log file {path}: {e}")
    # Return newest first
    return list(reversed(runs))


@router.get("/logs")
async def list_test_logs() -> Dict[str, Any]:
    """
    List all test log files, with status/elapsed from the most recent run.
    """
    try:
        test_suite_dir = Path(os.getenv("TEST_SUITE_DIR", "/testSuite"))

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
                runs = _parse_log_file(log_file)
                last_run = runs[0] if runs else {}

                # Build a short text preview from the last run
                preview = json.dumps(last_run)[:500] if last_run else ""

                logs.append({
                    "path": str(log_file),
                    "relative_path": str(log_file.relative_to(test_suite_dir)),
                    "size_bytes": log_file.stat().st_size,
                    "modified": log_file.stat().st_mtime,
                    "status": last_run.get("status", "UNKNOWN"),
                    "elapsed_ms": last_run.get("elapsed_ms", 0),
                    "run_count": len(runs),
                    "content_preview": preview,
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
    Get all run entries for a specific test (newest first).
    """
    try:
        test_suite_dir = Path(os.getenv("TEST_SUITE_DIR", "/testSuite"))

        log_files = list(test_suite_dir.rglob("*.test.log"))

        # Primary: fast filename-based match (test name is usually part of the file name)
        matching_logs = [lf for lf in log_files if test_id in lf.name]
        found_by_filename = bool(matching_logs)

        # Fallback: search inside each log file for a stored "test_name" that matches exactly.
        # This handles cases where the YAML filename differs from the test's "name:" field,
        # or where the test was renamed after its first run (so the first line of the file
        # may carry an old test name — we must scan ALL lines).
        if not matching_logs:
            # Sort by modification time, newest first, so we prefer the most-recently-used file
            for lf in sorted(log_files, key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    runs = _parse_log_file(lf)  # parses all lines; returns newest-first
                    if any(r.get("test_name") == test_id for r in runs):
                        matching_logs = [lf]
                        break
                except Exception:
                    pass

        if not matching_logs:
            raise HTTPException(
                status_code=404,
                detail=f"No log file found for test '{test_id}'"
            )

        log_file = matching_logs[0]
        runs = _parse_log_file(log_file)

        # Filter by test_name only when the file was found via the content-scan fallback
        # (i.e. the filename does NOT embed the test_id). This handles renamed tests where
        # one file may contain runs for multiple test names.
        # When the file was found by filename the test_name in log entries may legitimately
        # differ from the URL test_id (the YAML "name:" field vs the filename prefix), so
        # we must NOT filter in that case — all runs in the file belong to this test.
        if not found_by_filename:
            runs = [r for r in runs if r.get("test_name") == test_id or "test_name" not in r]

        return {
            "test_id": test_id,
            "log_path": str(log_file),
            "log_size_bytes": log_file.stat().st_size,
            "run_count": len(runs),
            "runs": runs,  # newest first
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving log for test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
