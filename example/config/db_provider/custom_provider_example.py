"""
Custom DB Provider Example
==========================

This file demonstrates how to implement a custom database provider and register it
so it can be referenced in databases.yaml as ``provider: postgresql``.

Place this file (or any .py file) in ``example/config/db_provider/``.
It will be auto-loaded at startup and hot-reloaded every 30 seconds.

To install the required library, add to example/config/python-requirements/requirements.txt:
    psycopg2-binary==2.9.9
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Import the base class and factory
# ---------------------------------------------------------------------------
try:
    from src.db.providers.base import DBProvider, DBResult, NotSupportedError
    from src.db.providers.factory import DBProviderFactory
except ImportError:
    # When loaded from inside the container the import path is without 'src.'
    from db.providers.base import DBProvider, DBResult, NotSupportedError  # type: ignore
    from db.providers.factory import DBProviderFactory  # type: ignore


# ---------------------------------------------------------------------------
# 2. Implement the provider
# ---------------------------------------------------------------------------

class PostgreSQLDBProvider(DBProvider):
    """
    Example PostgreSQL provider using psycopg2.

    Constructor kwargs must match the fields defined in databases.yaml:
        host, port, database, username, password, ssl, pool_min, pool_max
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        ssl: Optional[Dict[str, Any]] = None,
        pool_min: int = 1,
        pool_max: int = 5,
        **kwargs,
    ):
        self._host = host
        self._port = port
        self._database = database
        self._username = username
        self._password = password
        self._ssl = ssl or {}
        self._conn = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        import psycopg2
        kwargs: Dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "user": self._username,
            "password": self._password,
        }
        if self._database:
            kwargs["dbname"] = self._database
        if self._ssl:
            kwargs["sslmode"] = "verify-full"
            if self._ssl.get("ca_certs"):
                kwargs["sslrootcert"] = self._ssl["ca_certs"]
            if self._ssl.get("certfile"):
                kwargs["sslcert"] = self._ssl["certfile"]
            if self._ssl.get("keyfile"):
                kwargs["sslkey"] = self._ssl["keyfile"]
        self._conn = psycopg2.connect(**{k: v for k, v in kwargs.items() if v is not None})
        logger.info(f"PostgreSQL connected to {self._host}:{self._port}/{self._database}")

    def disconnect(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.closed

    def validate_connection(self) -> bool:
        try:
            result = self.select("SELECT 1")
            return len(result.rows) > 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # DML helpers
    # ------------------------------------------------------------------

    def _ensure(self):
        if not self.is_connected():
            self.connect()

    @staticmethod
    def _fetch_rows(cursor) -> List[Dict[str, Any]]:
        if cursor.description is None:
            return []
        cols = [col.name for col in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # DML operations
    # ------------------------------------------------------------------

    def select(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        self._ensure()
        cur = self._conn.cursor()
        cur.execute(query, params or {})
        rows = self._fetch_rows(cur)
        return DBResult(rows=rows, rows_affected=len(rows))

    def insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        self._ensure()
        cur = self._conn.cursor()
        # Append RETURNING to get generated key if not already present
        _q = query.rstrip().rstrip(";")
        if "returning" not in _q.lower():
            _q += " RETURNING *"
        cur.execute(_q, params or {})
        self._conn.commit()
        rows = self._fetch_rows(cur)
        generated_key = rows[0].get("id") if rows else None
        return DBResult(generated_key=generated_key, rows_affected=cur.rowcount)

    def update(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        self._ensure()
        cur = self._conn.cursor()
        cur.execute(query, params or {})
        self._conn.commit()
        return DBResult(rows_affected=cur.rowcount)

    def delete(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        self._ensure()
        cur = self._conn.cursor()
        cur.execute(query, params or {})
        self._conn.commit()
        return DBResult(rows_affected=cur.rowcount)


# ---------------------------------------------------------------------------
# 3. Register the provider under the name used in databases.yaml
# ---------------------------------------------------------------------------
try:
    DBProviderFactory.register_external_provider("postgresql", PostgreSQLDBProvider)
    logger.info("Registered custom DB provider: postgresql → PostgreSQLDBProvider")
except Exception as _e:
    logger.warning(f"Could not register PostgreSQL provider: {_e}")

