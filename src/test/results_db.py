"""
SQLite database for persisting test and send execution results.
"""
import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Stored execution result record."""
    id: Optional[str] = None
    type: str = 'test'  # 'test' or 'send'
    execution_ids: List[str] = None
    mode: str = 'sequential'
    repeat: int = 1
    repeat_mode: str = 'interleaved-repeats'
    parallel_workers: int = 1
    total: int = 0
    passed: int = 0  # For tests
    failed: int = 0
    completed: int = 0  # For sends
    skipped: int = 0
    elapsed_ms: int = 0
    results: str = ''  # JSON list of individual results
    status: str = 'SUCCESS'  # 'SUCCESS', 'FAILURE', 'PARTIAL'
    error_message: Optional[str] = None
    created_at: str = None
    updated_at: str = None

    def __post_init__(self):
        now = datetime.utcnow().isoformat()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now
        if self.execution_ids is None:
            self.execution_ids = []


class ResultsDatabase:
    """SQLite database manager for execution results."""

    def __init__(self, db_path: str = '/tmp/kafka-wiremock-results.db'):
        """
        Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS execution_results (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    execution_ids TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    repeat INTEGER NOT NULL,
                    repeat_mode TEXT NOT NULL,
                    parallel_workers INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    passed INTEGER NOT NULL,
                    failed INTEGER NOT NULL,
                    completed INTEGER NOT NULL,
                    skipped INTEGER NOT NULL,
                    elapsed_ms INTEGER NOT NULL,
                    results TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            # Create index for faster queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_type_created 
                ON execution_results(type, created_at)
            ''')
            conn.commit()
        logger.info(f"Results database initialized at {self.db_path}")

    def save_result(self, result: ExecutionResult) -> ExecutionResult:
        """
        Save or update execution result.

        Args:
            result: ExecutionResult to save

        Returns:
            Saved ExecutionResult with ID
        """
        import uuid
        if result.id is None:
            result.id = str(uuid.uuid4())

        result.updated_at = datetime.utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO execution_results
                (id, type, execution_ids, mode, repeat, repeat_mode, parallel_workers,
                 total, passed, failed, completed, skipped, elapsed_ms, results,
                 status, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                result.id,
                result.type,
                json.dumps(result.execution_ids),
                result.mode,
                result.repeat,
                result.repeat_mode,
                result.parallel_workers,
                result.total,
                result.passed,
                result.failed,
                result.completed,
                result.skipped,
                result.elapsed_ms,
                result.results,
                result.status,
                result.error_message,
                result.created_at,
                result.updated_at
            ))
            conn.commit()

        logger.info(f"Saved execution result: {result.id}")
        return result

    def get_result(self, result_id: str) -> Optional[ExecutionResult]:
        """
        Get execution result by ID.

        Args:
            result_id: Result ID

        Returns:
            ExecutionResult or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM execution_results WHERE id = ?', (result_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_result(row)
            return None

    def list_results(self, result_type: str = None, limit: int = 50, offset: int = 0) -> List[ExecutionResult]:
        """
        List execution results with optional filtering.

        Args:
            result_type: Filter by type ('test', 'send', or None for all)
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of ExecutionResult objects
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if result_type:
                cursor.execute('''
                    SELECT * FROM execution_results
                    WHERE type = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                ''', (result_type, limit, offset))
            else:
                cursor.execute('''
                    SELECT * FROM execution_results
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                ''', (limit, offset))

            rows = cursor.fetchall()
            return [self._row_to_result(row) for row in rows]

    def count_results(self, result_type: str = None) -> int:
        """
        Count total execution results.

        Args:
            result_type: Filter by type or None for all

        Returns:
            Total count
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if result_type:
                cursor.execute('SELECT COUNT(*) FROM execution_results WHERE type = ?', (result_type,))
            else:
                cursor.execute('SELECT COUNT(*) FROM execution_results')

            return cursor.fetchone()[0]

    def delete_result(self, result_id: str) -> bool:
        """
        Delete execution result by ID.

        Args:
            result_id: Result ID

        Returns:
            True if deleted, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM execution_results WHERE id = ?', (result_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_old_results(self, days: int = 30) -> int:
        """
        Delete results older than specified days.

        Args:
            days: Keep results from last N days

        Returns:
            Number of deleted records
        """
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM execution_results WHERE created_at < ?',
                (cutoff_date,)
            )
            conn.commit()
            deleted = cursor.rowcount

        logger.info(f"Deleted {deleted} execution results older than {days} days")
        return deleted

    def get_statistics(self, result_type: str = None, days: int = 30) -> Dict[str, Any]:
        """
        Get statistics for execution results.

        Args:
            result_type: Filter by type or None for all
            days: Only include results from last N days

        Returns:
            Statistics dictionary
        """
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if result_type:
                cursor.execute('''
                    SELECT
                        COUNT(*) as total_executions,
                        SUM(total) as total_items,
                        SUM(passed) as total_passed,
                        SUM(failed) as total_failed,
                        SUM(completed) as total_completed,
                        SUM(skipped) as total_skipped,
                        SUM(elapsed_ms) as total_time_ms,
                        AVG(elapsed_ms) as avg_time_ms
                    FROM execution_results
                    WHERE type = ? AND created_at >= ?
                ''', (result_type, cutoff_date))
            else:
                cursor.execute('''
                    SELECT
                        COUNT(*) as total_executions,
                        SUM(total) as total_items,
                        SUM(passed) as total_passed,
                        SUM(failed) as total_failed,
                        SUM(completed) as total_completed,
                        SUM(skipped) as total_skipped,
                        SUM(elapsed_ms) as total_time_ms,
                        AVG(elapsed_ms) as avg_time_ms
                    FROM execution_results
                    WHERE created_at >= ?
                ''', (cutoff_date,))

            row = cursor.fetchone()
            return {
                'total_executions': row[0] or 0,
                'total_items': row[1] or 0,
                'total_passed': row[2] or 0,
                'total_failed': row[3] or 0,
                'total_completed': row[4] or 0,
                'total_skipped': row[5] or 0,
                'total_time_ms': int(row[6]) if row[6] else 0,
                'avg_time_ms': int(row[7]) if row[7] else 0
            }

    def _row_to_result(self, row: sqlite3.Row) -> ExecutionResult:
        """Convert database row to ExecutionResult."""
        return ExecutionResult(
            id=row['id'],
            type=row['type'],
            execution_ids=json.loads(row['execution_ids']),
            mode=row['mode'],
            repeat=row['repeat'],
            repeat_mode=row['repeat_mode'],
            parallel_workers=row['parallel_workers'],
            total=row['total'],
            passed=row['passed'],
            failed=row['failed'],
            completed=row['completed'],
            skipped=row['skipped'],
            elapsed_ms=row['elapsed_ms'],
            results=row['results'],
            status=row['status'],
            error_message=row['error_message'],
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )

