"""
Database API endpoints.

GET  /api/db/status          — list all configured databases, their provider and pool stats
GET  /api/db/providers        — list available (installed) DB providers
POST /api/db/{db_ref}/query  — execute an ad-hoc query on a named database (for debugging)
"""
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/db", tags=["database"])

# --- module-level ref set by main.py -----------------------------------------
_db_registry = None


def set_db_registry(registry) -> None:
    global _db_registry
    _db_registry = registry


# --- request / response models -----------------------------------------------

class DBQueryRequest(BaseModel):
    operation: str = "select"       # select | insert | update | delete
    query: str
    params: Optional[Dict[str, Any]] = None
    step_id: Optional[str] = "adhoc"


class DBQueryResponse(BaseModel):
    db_ref: str
    operation: str
    rows: list = []
    generated_key: Any = None
    rows_affected: int = 0
    elapsed_ms: int = 0
    error: Optional[str] = None


# --- endpoints ----------------------------------------------------------------

@router.get("/status")
async def db_status():
    """
    List all configured databases with their provider type and pool statistics.
    """
    if _db_registry is None or _db_registry.is_empty():
        return {"databases": {}, "message": "No databases configured (see db-config/databases.yaml)"}
    return {"databases": _db_registry.get_status()}


@router.get("/providers")
async def db_providers():
    """
    List all DB providers and whether their driver library is installed.
    """
    if _db_registry is None:
        from ..db.providers.factory import DBProviderFactory
        return {"providers": DBProviderFactory.get_available_providers()}
    return {"providers": _db_registry.get_available_providers()}


@router.post("/{db_ref}/query", response_model=DBQueryResponse)
async def db_query(db_ref: str, request: DBQueryRequest):
    """
    Execute an ad-hoc query on a named database.

    Useful for debugging and one-off data operations.
    **Note**: template placeholders (``{{...}}``) are NOT rendered here —
    the raw query is sent directly to the provider.
    """
    if _db_registry is None or _db_registry.is_empty():
        raise HTTPException(
            status_code=503,
            detail="DB registry not initialised. Configure databases in db-config/databases.yaml.",
        )

    if db_ref not in _db_registry.get_all_names():
        raise HTTPException(
            status_code=404,
            detail=f"Database '{db_ref}' not found. "
                   f"Available: {', '.join(_db_registry.get_all_names())}",
        )

    logger.info(
        f"Ad-hoc DB query: db={db_ref!r} operation={request.operation!r} "
        f"query={request.query!r}"
    )

    from ..db.executor import DBExecutor
    executor = DBExecutor(_db_registry)

    start = time.time()
    try:
        ctx = executor.execute(
            db_ref=db_ref,
            operation=request.operation,
            query=request.query,
            params=request.params,
            step_id=request.step_id,
        )
        elapsed = int((time.time() - start) * 1000)

        prefix = f"db.{request.step_id}"
        rows = ctx.get(f"{prefix}.rows", [])
        generated_key = ctx.get(f"{prefix}.generated_key")
        rows_affected = ctx.get(f"{prefix}.rows_affected", 0)

        return DBQueryResponse(
            db_ref=db_ref,
            operation=request.operation,
            rows=rows,
            generated_key=generated_key,
            rows_affected=rows_affected,
            elapsed_ms=elapsed,
        )
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        logger.error(f"Ad-hoc DB query failed for '{db_ref}': {e}")
        return DBQueryResponse(
            db_ref=db_ref,
            operation=request.operation,
            elapsed_ms=elapsed,
            error=str(e),
        )

