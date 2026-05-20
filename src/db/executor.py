"""
DB Executor — renders templates in DB actions and dispatches to providers.

Context population after each step:
    select  → db.<id>.<col>  (first row columns), db.<id>.rows (all rows), db.<id>.row_count
    insert  → db.<id>.generated_key, db.<id>.rows_affected
    update  → db.<id>.rows_affected
    delete  → db.<id>.rows_affected
"""
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

from .providers.base import DBResult

if TYPE_CHECKING:
    from .registry import DBRegistry

logger = logging.getLogger(__name__)

# Supported operation names
OPERATIONS = {"select", "insert", "update", "delete"}


class DBExecutor:
    """
    Executes DB actions described by TestDBAction / Output (type=db).

    Rendering of ``{{...}}`` placeholders in query/params is done by the
    caller (TestSuiteRunner / KafkaListenerEngine) before calling here, OR
    this executor handles it if a TemplateRenderer is passed in.
    """

    def __init__(self, db_registry: "DBRegistry"):
        self._registry = db_registry

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def execute(
        self,
        *,
        db_ref: str,
        operation: str,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        step_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute one DB action and return a context-update dict.

        Args:
            db_ref:    Registry key (e.g. 'onepam', 'someCassandra').
            operation: 'select' | 'insert' | 'update' | 'delete'.
            query:     Rendered SQL/CQL string (placeholders already resolved).
            params:    Optional named bind parameters dict (values already rendered).
            step_id:   Step identifier used as prefix for context keys.
                       Required for 'select' and 'insert' (to surface result values).
                       Optional for 'update' / 'delete'.

        Returns:
            Dict of context keys to merge into the template context.
            Keys use the pattern ``db.<step_id>.*``.
        """
        operation = operation.lower()
        if operation not in OPERATIONS:
            raise ValueError(
                f"DB operation '{operation}' is not valid. "
                f"Supported: {', '.join(sorted(OPERATIONS))}"
            )

        provider = self._registry.get_provider(db_ref)
        try:
            result = self._dispatch(provider, operation, query, params)
        finally:
            self._registry.release_provider(db_ref, provider)

        return self._build_context(step_id, operation, result)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    @staticmethod
    def _dispatch(
        provider,
        operation: str,
        query: str,
        params: Optional[Dict[str, Any]],
    ) -> DBResult:
        if operation == "select":
            return provider.select(query, params)
        elif operation == "insert":
            return provider.insert(query, params)
        elif operation == "update":
            return provider.update(query, params)
        elif operation == "delete":
            return provider.delete(query, params)
        # Should not be reached (validated above)
        raise ValueError(f"Unknown operation: {operation}")

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(
        step_id: Optional[str],
        operation: str,
        result: DBResult,
    ) -> Dict[str, Any]:
        """
        Turn a DBResult into a flat context dict.

        All keys are prefixed with ``db.<step_id>.`` when step_id is present.
        """
        if not step_id:
            # No step_id: nothing to expose; just log the outcome
            logger.debug(
                f"DB {operation}: rows_affected={result.rows_affected} "
                f"(no step_id — result not stored in context)"
            )
            return {}

        prefix = f"db.{step_id}"
        ctx: Dict[str, Any] = {}

        if operation == "select":
            # First-row columns as top-level keys for easy access
            first_row = result.rows[0] if result.rows else {}
            for col, val in first_row.items():
                ctx[f"{prefix}.{col}"] = val
            # Full row list  (accessible from scripts / custom placeholders)
            ctx[f"{prefix}.rows"] = result.rows
            ctx[f"{prefix}.row_count"] = len(result.rows)

        elif operation == "insert":
            ctx[f"{prefix}.generated_key"] = result.generated_key
            ctx[f"{prefix}.rows_affected"] = result.rows_affected

        else:  # update / delete
            ctx[f"{prefix}.rows_affected"] = result.rows_affected

        logger.debug(
            f"DB {operation} step='{step_id}': "
            f"rows={len(result.rows)} affected={result.rows_affected} "
            f"generated_key={result.generated_key} "
            f"context_keys={list(ctx.keys())}"
        )
        return ctx

