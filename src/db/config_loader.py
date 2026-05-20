"""
DB configuration loader.

Reads ``{config_dir}/db-config/databases.yaml``.
Passwords are resolved from environment variables:
    DB_<NAME_UPPER>_PASSWORD          (main password)
    DB_<NAME_UPPER>_WALLET_PASSWORD   (Oracle wallet password)

Also hot-loads custom provider .py files from ``{provider_dir}/`` every
``scan_interval`` seconds by importing them with importlib; each file
is expected to call DBProviderFactory.register_external_provider(...).
"""
import hashlib
import importlib.util
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .pool import DBPoolConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class DBDatabaseConfig:
    """Parsed configuration for one database entry in databases.yaml."""
    name: str
    provider: str                               # 'oracle' | 'mysql' | 'cassandra' | custom

    # Common
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None             # resolved from env var

    # Oracle-specific
    service_name: Optional[str] = None
    dsn: Optional[str] = None

    # MySQL-specific
    database: Optional[str] = None

    # Cassandra-specific
    contact_points: Optional[List[str]] = None
    keyspace: Optional[str] = None

    # Security
    ssl: Optional[Dict[str, Any]] = None        # ssl sub-dict (cert paths, etc.)

    # Pool
    pool: DBPoolConfig = field(default_factory=DBPoolConfig)

    def to_provider_config(self) -> Dict[str, Any]:
        """
        Build the kwargs dict forwarded to the provider constructor.

        Passwords are included here (the registry/factory receive them; they are
        never logged or serialised for API responses).
        """
        cfg: Dict[str, Any] = {
            "username": self.username,
            "password": self.password,
            "ssl": self.ssl,
            "pool_min": self.pool.min_size,
            "pool_max": self.pool.max_size,
        }
        if self.host is not None:
            cfg["host"] = self.host
        if self.port is not None:
            cfg["port"] = self.port
        # Oracle
        if self.service_name:
            cfg["service_name"] = self.service_name
        if self.dsn:
            cfg["dsn"] = self.dsn
        # MySQL
        if self.database:
            cfg["database"] = self.database
        # Cassandra
        if self.contact_points:
            cfg["contact_points"] = self.contact_points
        if self.keyspace:
            cfg["keyspace"] = self.keyspace
        return {k: v for k, v in cfg.items() if v is not None}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class DBConfigLoader:
    """
    Loads databases.yaml and hot-loads external provider files.

    Usage:
        loader = DBConfigLoader(config_dir="/config/db-config",
                                provider_dir="/config/db_provider")
        configs = loader.load()          # Dict[str, DBDatabaseConfig]
        loader.start_hot_reload()        # background provider hot-reload
        loader.stop()
    """

    def __init__(
        self,
        config_dir: str = "/config/db-config",
        provider_dir: str = "/config/db_provider",
        scan_interval: int = 30,
    ):
        self._config_dir = Path(config_dir)
        self._provider_dir = Path(provider_dir)
        self._scan_interval = scan_interval
        self._db_file = self._config_dir / "databases.yaml"

        self._file_hashes: Dict[Path, str] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._provider_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, DBDatabaseConfig]:
        """
        Parse databases.yaml and return a dict of name → DBDatabaseConfig.

        Returns empty dict if the file does not exist.
        """
        if not self._db_file.exists():
            logger.info(
                f"databases.yaml not found at {self._db_file} — no databases configured"
            )
            return {}

        try:
            with open(self._db_file, "r") as fh:
                raw = yaml.safe_load(fh)
        except Exception as e:
            logger.error(f"Failed to read databases.yaml: {e}")
            return {}

        if not isinstance(raw, dict) or "databases" not in raw:
            logger.warning("databases.yaml must have a top-level 'databases' key")
            return {}

        db_dict = raw.get("databases") or {}
        configs: Dict[str, DBDatabaseConfig] = {}
        for db_name, db_cfg in db_dict.items():
            try:
                configs[db_name] = self._parse_entry(db_name, db_cfg or {})
                logger.info(f"Loaded DB config: '{db_name}' (provider={configs[db_name].provider})")
            except Exception as e:
                logger.error(f"Failed to parse DB config for '{db_name}': {e}")

        return configs

    def load_external_providers(self) -> None:
        """
        Import / re-import all .py files from the provider_dir.

        Each file calls DBProviderFactory.register_external_provider() on load.
        Files are tracked by hash so only changed files are re-imported.
        """
        py_files = sorted(self._provider_dir.glob("*.py"))
        for py_file in py_files:
            try:
                current_hash = self._file_hash(py_file)
                if self._file_hashes.get(py_file) == current_hash:
                    continue  # unchanged
                self._import_provider_file(py_file)
                self._file_hashes[py_file] = current_hash
            except Exception as e:
                logger.error(f"Failed to load provider file '{py_file.name}': {e}")

    def start_hot_reload(self) -> None:
        """Start background thread that rescans provider_dir every scan_interval seconds."""
        if self._running:
            return
        # Run initial load immediately
        self.load_external_providers()
        self._running = True
        self._thread = threading.Thread(
            target=self._scan_loop, daemon=True, name="db-provider-hot-reload"
        )
        self._thread.start()
        logger.info(f"DB provider hot-reload started (interval={self._scan_interval}s)")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _scan_loop(self) -> None:
        import time
        while self._running:
            time.sleep(self._scan_interval)
            if not self._running:
                break
            try:
                self.load_external_providers()
            except Exception as e:
                logger.error(f"Error in DB provider hot-reload loop: {e}")

    def _parse_entry(self, name: str, cfg: Dict[str, Any]) -> DBDatabaseConfig:
        provider = str(cfg.get("provider", "")).lower()
        if not provider:
            raise ValueError(f"DB entry '{name}' missing 'provider' field")

        # Resolve password from environment
        env_key = f"DB_{name.upper()}_PASSWORD"
        password = os.getenv(env_key, cfg.get("password"))
        if cfg.get("password") and not os.getenv(env_key):
            # Password from YAML is allowed but warn
            logger.warning(
                f"DB '{name}': password found in YAML. "
                f"Prefer env var {env_key} for security."
            )

        # Oracle wallet password
        ssl_cfg = dict(cfg.get("ssl") or {})
        wallet_env_key = f"DB_{name.upper()}_WALLET_PASSWORD"
        if os.getenv(wallet_env_key):
            ssl_cfg["wallet_password"] = os.getenv(wallet_env_key)

        # Pool config
        pool_raw = cfg.get("pool") or {}
        pool = DBPoolConfig(
            min_size=int(pool_raw.get("min_size", 1)),
            max_size=int(pool_raw.get("max_size", 5)),
            acquire_timeout_s=float(pool_raw.get("acquire_timeout_s", 10.0)),
            validate_on_borrow=bool(pool_raw.get("validate_on_borrow", True)),
        )

        # contact_points: accept string or list
        contact_points = cfg.get("contact_points")
        if isinstance(contact_points, str):
            contact_points = [contact_points]

        return DBDatabaseConfig(
            name=name,
            provider=provider,
            host=cfg.get("host"),
            port=int(cfg["port"]) if cfg.get("port") else None,
            username=cfg.get("username"),
            password=password,
            service_name=cfg.get("service_name"),
            dsn=cfg.get("dsn"),
            database=cfg.get("database"),
            contact_points=contact_points,
            keyspace=cfg.get("keyspace"),
            ssl=ssl_cfg if ssl_cfg else None,
            pool=pool,
        )

    @staticmethod
    def _import_provider_file(py_file: Path) -> None:
        module_name = f"_db_provider_{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {py_file}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        logger.info(f"Loaded external DB provider file: {py_file.name}")

    @staticmethod
    def _file_hash(path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(4096), b""):
                sha.update(chunk)
        return sha.hexdigest()

