"""
MySQL DB provider.

Uses ``mysql-connector-python``.

SSL support:
  ssl:
    ca_certs: /path/to/ca.pem      (ssl_ca)
    certfile: /path/to/client.pem  (ssl_cert)
    keyfile: /path/to/client.key   (ssl_key)
    verify_cert: true              (default true — set false to skip validation)
"""
import logging
from typing import Any, Dict, List, Optional

from .base import DBProvider, DBResult, NotSupportedError

logger = logging.getLogger(__name__)


class MySQLDBProvider(DBProvider):
    """
    MySQL / MariaDB database provider via mysql-connector-python.

    Constructor keyword args mirror the ``databases.yaml`` fields:
        host, port, database, username, password, ssl, pool_min, pool_max
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
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
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pool = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _build_connect_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "user": self._username,
            "password": self._password,
        }
        if self._database:
            kwargs["database"] = self._database
        if self._ssl:
            ssl_cfg: Dict[str, Any] = {}
            if self._ssl.get("ca_certs"):
                ssl_cfg["ssl_ca"] = self._ssl["ca_certs"]
            if self._ssl.get("certfile"):
                ssl_cfg["ssl_cert"] = self._ssl["certfile"]
            if self._ssl.get("keyfile"):
                ssl_cfg["ssl_key"] = self._ssl["keyfile"]
            verify = self._ssl.get("verify_cert", True)
            ssl_cfg["ssl_verify_cert"] = bool(verify)
            kwargs.update(ssl_cfg)
        return {k: v for k, v in kwargs.items() if v is not None}

    def connect(self) -> None:
        try:
            import mysql.connector
            from mysql.connector import pooling
        except ImportError:
            raise ImportError(
                "MySQL driver not found. Install with: pip install mysql-connector-python"
            )
        try:
            connect_kwargs = self._build_connect_kwargs()
            self._pool = pooling.MySQLConnectionPool(
                pool_name="kwmock",
                pool_size=self._pool_max,
                **connect_kwargs,
            )
            logger.info(f"MySQL connection pool created (pool_size={self._pool_max})")
        except Exception as e:
            raise ConnectionError(f"MySQL connect failed: {e}") from e

    def disconnect(self) -> None:
        # mysql-connector-python pools don't expose an explicit close_all,
        # but setting to None lets GC clean up.
        self._pool = None
        logger.info("MySQL connection pool released")

    def is_connected(self) -> bool:
        return self._pool is not None

    def validate_connection(self) -> bool:
        try:
            result = self.select("SELECT 1")
            return len(result.rows) > 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_connection(self):
        if not self._pool:
            self.connect()
        return self._pool.get_connection()

    @staticmethod
    def _cursor_rows(cursor) -> List[Dict[str, Any]]:
        if cursor.description is None:
            return []
        columns = [col[0].lower() for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # DML operations
    # ------------------------------------------------------------------

    def select(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or {})
            rows = self._cursor_rows(cursor)
            return DBResult(rows=rows, rows_affected=len(rows))
        except Exception as e:
            raise RuntimeError(f"MySQL SELECT failed: {e}") from e
        finally:
            try:
                conn.close()  # returns to pool
            except Exception:
                pass

    def insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or {})
            conn.commit()
            generated_key = cursor.lastrowid if cursor.lastrowid else None
            return DBResult(generated_key=generated_key, rows_affected=cursor.rowcount)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise RuntimeError(f"MySQL INSERT failed: {e}") from e
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def update(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or {})
            conn.commit()
            return DBResult(rows_affected=cursor.rowcount)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise RuntimeError(f"MySQL UPDATE failed: {e}") from e
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def delete(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or {})
            conn.commit()
            return DBResult(rows_affected=cursor.rowcount)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise RuntimeError(f"MySQL DELETE failed: {e}") from e
        finally:
            try:
                conn.close()
            except Exception:
                pass

