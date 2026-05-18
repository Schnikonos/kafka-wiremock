"""
Oracle DB provider.

Uses the ``oracledb`` thin-mode library (no Oracle Client required).
Falls back to ``cx_Oracle`` if ``oracledb`` is not installed.

SSL / wallet support:
  ssl:
    wallet_location: /opt/oracle/wallet
    wallet_password: ...          # or env DB_<NAME_UPPER>_WALLET_PASSWORD
    ssl_server_dn_match: true     # default true
    ssl_server_cert_dn: ""        # optional Distinguished Name
"""
import logging
from typing import Any, Dict, List, Optional

from .base import DBProvider, DBResult, NotSupportedError

logger = logging.getLogger(__name__)


class OracleDBProvider(DBProvider):
    """
    Oracle database provider.

    Constructor keyword args mirror the ``databases.yaml`` fields:
        host, port, service_name, dsn, username, password, ssl, pool_min, pool_max
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 1521,
        service_name: Optional[str] = None,
        dsn: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        ssl: Optional[Dict[str, Any]] = None,
        pool_min: int = 1,
        pool_max: int = 5,
        **kwargs,  # absorb unknown config keys gracefully
    ):
        self._host = host
        self._port = port
        self._service_name = service_name
        self._dsn = dsn
        self._username = username
        self._password = password
        self._ssl = ssl or {}
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pool = None
        self._lib = None  # oracledb or cx_Oracle module

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _get_lib(self):
        if self._lib is None:
            try:
                import oracledb
                self._lib = oracledb
            except ImportError:
                try:
                    import cx_Oracle as oracledb  # noqa: N813
                    self._lib = oracledb
                except ImportError:
                    raise ImportError(
                        "Oracle driver not found. Install with: "
                        "pip install oracledb  (or pip install cx_Oracle)"
                    )
        return self._lib

    def _build_dsn(self):
        lib = self._get_lib()
        if self._dsn:
            return self._dsn
        if self._host and self._service_name:
            return lib.makedsn(self._host, self._port, service_name=self._service_name)
        raise ValueError(
            "Oracle provider requires either 'dsn' or both 'host' and 'service_name'"
        )

    def _build_connect_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "user": self._username,
            "password": self._password,
            "dsn": self._build_dsn(),
        }
        if self._ssl:
            kwargs["wallet_location"] = self._ssl.get("wallet_location")
            if self._ssl.get("wallet_password"):
                kwargs["wallet_password"] = self._ssl["wallet_password"]
            # ssl_server_dn_match defaults to True (secure)
            dn_match = self._ssl.get("ssl_server_dn_match", True)
            kwargs["ssl_server_dn_match"] = dn_match
            if self._ssl.get("ssl_server_cert_dn"):
                kwargs["ssl_server_cert_dn"] = self._ssl["ssl_server_cert_dn"]
        return {k: v for k, v in kwargs.items() if v is not None}

    def connect(self) -> None:
        lib = self._get_lib()
        connect_kwargs = self._build_connect_kwargs()
        try:
            if hasattr(lib, "create_pool"):
                # oracledb / cx_Oracle pool API
                pool_kwargs = {
                    **connect_kwargs,
                    "min": self._pool_min,
                    "max": self._pool_max,
                    "increment": 1,
                }
                self._pool = lib.create_pool(**pool_kwargs)
                logger.info(
                    f"Oracle connection pool created (min={self._pool_min}, max={self._pool_max})"
                )
            else:
                # Fallback: plain single connection
                self._pool = lib.connect(**connect_kwargs)
                logger.info("Oracle single connection established")
        except Exception as e:
            raise ConnectionError(f"Oracle connect failed: {e}") from e

    def disconnect(self) -> None:
        if self._pool:
            try:
                self._pool.close()
                logger.info("Oracle connection pool closed")
            except Exception as e:
                logger.warning(f"Oracle disconnect error: {e}")
            finally:
                self._pool = None

    def is_connected(self) -> bool:
        return self._pool is not None

    def validate_connection(self) -> bool:
        try:
            result = self.select("SELECT 1 FROM DUAL")
            return len(result.rows) > 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_connection(self):
        if not self._pool:
            self.connect()
        if hasattr(self._pool, "acquire"):
            return self._pool.acquire()
        return self._pool  # plain connection

    def _release_connection(self, conn) -> None:
        if hasattr(self._pool, "release"):
            try:
                self._pool.release(conn)
            except Exception:
                pass

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
            raise RuntimeError(f"Oracle SELECT failed: {e}") from e
        finally:
            self._release_connection(conn)

    def insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or {})
            conn.commit()
            generated_key = cursor.lastrowid if hasattr(cursor, "lastrowid") else None
            return DBResult(generated_key=generated_key, rows_affected=cursor.rowcount)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise RuntimeError(f"Oracle INSERT failed: {e}") from e
        finally:
            self._release_connection(conn)

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
            raise RuntimeError(f"Oracle UPDATE failed: {e}") from e
        finally:
            self._release_connection(conn)

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
            raise RuntimeError(f"Oracle DELETE failed: {e}") from e
        finally:
            self._release_connection(conn)

