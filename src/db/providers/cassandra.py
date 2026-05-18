"""
Apache Cassandra / ScyllaDB provider.

Uses ``cassandra-driver``.

Notes:
  - Cassandra has no auto-generated primary key concept (UUIDs are application-side).
    ``insert()`` returns ``generated_key=None`` unless the query contains a ``RETURNING``-like
    workaround (not standard CQL).  Users should generate UUIDs via ``{{uuid}}`` in the query.
  - ``update()`` and ``delete()`` are fully supported via CQL.
  - Named bind parameters use the ``%(name)s`` style accepted by the cassandra-driver.

SSL support:
  ssl:
    ca_certs:    /path/to/ca.pem
    certfile:    /path/to/client.pem
    keyfile:     /path/to/client.key
    check_hostname: false          (default false for Cassandra)
"""
import logging
import ssl as _ssl_mod
from typing import Any, Dict, List, Optional

from .base import DBProvider, DBResult, NotSupportedError

logger = logging.getLogger(__name__)


class CassandraDBProvider(DBProvider):
    """
    Cassandra (+ ScyllaDB compatible) database provider.

    Constructor keyword args mirror the ``databases.yaml`` fields:
        contact_points, port, keyspace, username, password, ssl, pool_min, pool_max
    """

    def __init__(
        self,
        contact_points: Optional[List[str]] = None,
        port: int = 9042,
        keyspace: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        ssl: Optional[Dict[str, Any]] = None,
        pool_min: int = 1,
        pool_max: int = 5,
        **kwargs,
    ):
        self._contact_points = contact_points or ["localhost"]
        self._port = port
        self._keyspace = keyspace
        self._username = username
        self._password = password
        self._ssl = ssl or {}
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._cluster = None
        self._session = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _build_ssl_context(self) -> Optional[Any]:
        if not self._ssl:
            return None
        try:
            ctx = _ssl_mod.SSLContext(_ssl_mod.PROTOCOL_TLS_CLIENT)
            if self._ssl.get("ca_certs"):
                ctx.load_verify_locations(self._ssl["ca_certs"])
            if self._ssl.get("certfile") and self._ssl.get("keyfile"):
                ctx.load_cert_chain(self._ssl["certfile"], self._ssl["keyfile"])
            ctx.check_hostname = bool(self._ssl.get("check_hostname", False))
            if not ctx.check_hostname:
                ctx.verify_mode = _ssl_mod.CERT_NONE
            return ctx
        except Exception as e:
            logger.warning(f"Cassandra SSL context build failed: {e}")
            return None

    def connect(self) -> None:
        try:
            from cassandra.cluster import Cluster
            from cassandra.auth import PlainTextAuthProvider
            from cassandra.policies import RoundRobinPolicy
        except ImportError:
            raise ImportError(
                "Cassandra driver not found. Install with: pip install cassandra-driver"
            )
        try:
            kwargs: Dict[str, Any] = {
                "contact_points": self._contact_points,
                "port": self._port,
                "load_balancing_policy": RoundRobinPolicy(),
            }
            if self._username and self._password:
                kwargs["auth_provider"] = PlainTextAuthProvider(
                    username=self._username, password=self._password
                )
            ssl_ctx = self._build_ssl_context()
            if ssl_ctx:
                kwargs["ssl_context"] = ssl_ctx

            self._cluster = Cluster(**kwargs)
            self._session = (
                self._cluster.connect(self._keyspace)
                if self._keyspace
                else self._cluster.connect()
            )
            logger.info(
                f"Cassandra connected to {self._contact_points} "
                f"(keyspace={self._keyspace or 'none'})"
            )
        except Exception as e:
            raise ConnectionError(f"Cassandra connect failed: {e}") from e

    def disconnect(self) -> None:
        if self._session:
            try:
                self._session.shutdown()
            except Exception as e:
                logger.warning(f"Cassandra session shutdown error: {e}")
            finally:
                self._session = None
        if self._cluster:
            try:
                self._cluster.shutdown()
            except Exception as e:
                logger.warning(f"Cassandra cluster shutdown error: {e}")
            finally:
                self._cluster = None
        logger.info("Cassandra connection closed")

    def is_connected(self) -> bool:
        return self._session is not None and not getattr(self._session, "is_shutdown", False)

    def validate_connection(self) -> bool:
        try:
            result = self._session.execute("SELECT release_version FROM system.local")
            return result is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self):
        if not self.is_connected():
            self.connect()

    @staticmethod
    def _result_rows(result_set) -> List[Dict[str, Any]]:
        if result_set is None:
            return []
        return [row._asdict() if hasattr(row, "_asdict") else dict(row) for row in result_set]

    # ------------------------------------------------------------------
    # DML operations
    # ------------------------------------------------------------------

    def select(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        self._ensure_connected()
        try:
            result_set = (
                self._session.execute(query, params) if params else self._session.execute(query)
            )
            rows = self._result_rows(result_set)
            return DBResult(rows=rows, rows_affected=len(rows))
        except Exception as e:
            raise RuntimeError(f"Cassandra SELECT failed: {e}") from e

    def insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        self._ensure_connected()
        try:
            self._session.execute(query, params) if params else self._session.execute(query)
            # Cassandra has no server-side auto-increment; generated_key = None
            return DBResult(generated_key=None, rows_affected=1)
        except Exception as e:
            raise RuntimeError(f"Cassandra INSERT failed: {e}") from e

    def update(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        self._ensure_connected()
        try:
            self._session.execute(query, params) if params else self._session.execute(query)
            return DBResult(rows_affected=1)
        except Exception as e:
            raise RuntimeError(f"Cassandra UPDATE failed: {e}") from e

    def delete(self, query: str, params: Optional[Dict[str, Any]] = None) -> DBResult:
        self._ensure_connected()
        try:
            self._session.execute(query, params) if params else self._session.execute(query)
            return DBResult(rows_affected=1)
        except Exception as e:
            raise RuntimeError(f"Cassandra DELETE failed: {e}") from e

