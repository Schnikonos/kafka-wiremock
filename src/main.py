"""
FastAPI application for Kafka Wiremock with Kafka and JMS support.

Main entry point that initializes the application and includes all API routers.
For endpoint implementations, see src/api/ package.
"""
import logging
import os
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from .config.loader import ConfigLoader
from .config.app_settings import AppSettingsLoader
from .config.jms_config_loader import JMSConfigLoader
from .config.queue_manager_loader import QueueManagerConfigLoader  # NEW
from .jms.registry import JMSClientRegistry  # NEW
from .kafka.client import KafkaClientWrapper
from .kafka.listener import KafkaListenerEngine
from .custom.placeholders import CustomPlaceholderRegistry
from .rules.templater import set_custom_placeholder_registry
from .test.loader import TestLoader
from .test.suite import TestSuiteRunner
from .test.jobs import TestJobManager
from .test.cache import MessageCache
from .test.listener_manager import TestListenerManager
from .test.results_db import ResultsDatabase
from .dependencies.manager import DependencyManager
from .send.loader import SendLoader
from .send.executor import SendExecutor
from .http.executor import HttpExecutor
from .config.mock_server_config import MockServerConfigLoader
from .http.stub_cache import HttpStubCache
from .http.mock_dispatch import MockDispatchHandler
from .http.mock_server import HttpMockServer
from .http.mock_server_registry import HttpMockServerRegistry

# Import API routers and setter functions
from .api import health, kafka_injection, rules, custom_placeholders, dependencies_mgmt, results, app_settings, config, jms as jms_api, db as db_api
from .api.tests import discovery, execution, jobs, logs, bulk, load as load_tests
from .api.send import discovery as send_discovery, execution as send_execution, bulk as send_bulk
from .api.debug import decode, match, topics, cache, template
from .jms.providers.factory import ProviderFactory  # NEW: provider factory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
config_loader: Optional[ConfigLoader] = None
app_settings_loader: Optional[AppSettingsLoader] = None
qm_config_loader: Optional[QueueManagerConfigLoader] = None  # NEW
jms_config_loader: Optional[JMSConfigLoader] = None
jms_registry: Optional[JMSClientRegistry] = None  # NEW: registry instead of single client
kafka_client: Optional[KafkaClientWrapper] = None
listener_engine: Optional[KafkaListenerEngine] = None
jms_listener_engine: Optional[object] = None  # JMSListenerEngine type
custom_placeholder_registry: Optional[CustomPlaceholderRegistry] = None
test_loader: Optional[TestLoader] = None
test_suite_runner: Optional[TestSuiteRunner] = None
test_job_manager: Optional[TestJobManager] = None
dependency_manager: Optional[DependencyManager] = None
message_cache: Optional[MessageCache] = None
test_listener_manager: Optional[TestListenerManager] = None
send_loader: Optional[SendLoader] = None
send_executor: Optional[SendExecutor] = None
http_executor: Optional[HttpExecutor] = None
results_db: Optional[ResultsDatabase] = None
mock_server_config_loader: Optional[MockServerConfigLoader] = None
http_stub_cache: Optional[HttpStubCache] = None
mock_dispatch_handler: Optional[MockDispatchHandler] = None
mock_server_registry: Optional[HttpMockServerRegistry] = None
db_config_loader = None
db_registry = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup and shutdown."""
    global config_loader, app_settings_loader, qm_config_loader, jms_config_loader, jms_registry, kafka_client, listener_engine, jms_listener_engine, custom_placeholder_registry, test_loader, test_suite_runner, test_job_manager, dependency_manager, message_cache, test_listener_manager, send_loader, send_executor, http_executor, results_db, mock_server_config_loader, http_stub_cache, mock_dispatch_handler, mock_server_registry, db_config_loader, db_registry
    # Startup
    logger.info("Starting Kafka Wiremock...")
    try:
        # Get Kafka bootstrap servers from environment
        bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        config_dir = os.getenv("CONFIG_DIR", "/config")
        test_suite_dir = os.getenv("TEST_SUITE_DIR", "/testSuite")
        custom_placeholders_dir = os.getenv("CUSTOM_PLACEHOLDERS_DIR", "/config/custom_placeholders")
        python_requirements_dir = os.getenv("PYTHON_REQUIREMENTS_DIR", "/config/python-requirements")
        python_requirements_scan_interval = int(os.getenv("PYTHON_REQUIREMENTS_SCAN_INTERVAL", "30"))

        # Initialize app settings loader
        app_settings_loader = AppSettingsLoader(config_dir=config_dir, scan_interval=30)
        app_settings_loader.start()

        # Initialize custom placeholder registry
        custom_placeholder_registry = CustomPlaceholderRegistry(config_dir=custom_placeholders_dir)
        set_custom_placeholder_registry(custom_placeholder_registry)

        # Initialize dependency manager (background thread)
        dependency_manager = DependencyManager(
            requirements_dir=python_requirements_dir,
            scan_interval=python_requirements_scan_interval
        )
        dependency_manager.start()

        # Initialize Kafka components
        config_loader = ConfigLoader(config_dir=config_dir, reload_interval=5)
        kafka_client = KafkaClientWrapper(bootstrap_servers=bootstrap_servers)

        # Initialize JMS components (optional) - NEW: multi-QM support with pooling
        jms_config_loader = JMSConfigLoader(config_dir=config_dir)
        qm_config_loader = QueueManagerConfigLoader(config_dir=config_dir)  # NEW

        # NEW: Create pool configuration
        from .jms.pool import PoolConfig
        pool_config = PoolConfig(
            min_idle=int(os.getenv("JMS_POOL_MIN_IDLE", "1")),
            max_size=int(os.getenv("JMS_POOL_MAX_SIZE", "5")),
            max_wait_ms=int(os.getenv("JMS_POOL_MAX_WAIT_MS", "5000")),
            auto_reconnect=os.getenv("JMS_POOL_AUTO_RECONNECT", "true").lower() == "true",
            reconnect_attempts=int(os.getenv("JMS_POOL_RECONNECT_ATTEMPTS", "3")),
            reconnect_delay_ms=int(os.getenv("JMS_POOL_RECONNECT_DELAY_MS", "1000"))
        )

        jms_registry = JMSClientRegistry(
            enable_pooling=os.getenv("JMS_POOLING_ENABLED", "true").lower() == "true",
            pool_config=pool_config
        )  # NEW: registry for multiple clients with pooling

        # Load queue manager configurations from queue-managers.yaml
        qm_configs = qm_config_loader.load()  # NEW

        if qm_configs:  # NEW: Only initialize if we have queue manager configs
            try:
                # Initialize each queue manager from config
                for qm_name, qm_config in qm_configs.items():  # NEW
                    try:
                        # Use provider factory to create appropriate client
                        provider_type = qm_config.provider or "ibm_mq"

                        # Build config dict for provider
                        provider_config = {
                            "broker_url": qm_config.broker_url,
                            "username": qm_config.username,
                            "password": qm_config.password,
                        }

                        # Add provider-specific fields
                        if provider_type == "ibm_mq":
                            provider_config["channel"] = qm_config.channel
                            provider_config["queue_manager"] = qm_config.queue_manager
                            if hasattr(qm_config, 'ssl_key_store'):
                                provider_config["ssl_key_store"] = qm_config.ssl_key_store
                                provider_config["ssl_key_store_password"] = qm_config.ssl_key_store_password
                        elif provider_type == "activemq":
                            provider_config["vhost"] = getattr(qm_config, 'vhost', "/")
                        elif provider_type == "rabbitmq":
                            provider_config["virtual_host"] = getattr(qm_config, 'virtual_host', "/")

                        # Create client using provider factory
                        client = ProviderFactory.create(provider_type, provider_config)
                        jms_registry.add_queue_manager(qm_name, client, config={
                            "provider": provider_type,
                            **provider_config
                        })  # NEW: pass config
                        logger.info(f"Registered {provider_type} JMS client for queue manager: {qm_name}")
                    except Exception as e:
                        logger.warning(
                            f"Failed to initialize queue manager '{qm_name}': {e}. "
                            f"This queue manager will be skipped."
                        )

                if not jms_registry.is_empty():  # NEW
                    logger.info(
                        f"Initialized {len(jms_registry.clients)} JMS queue manager(s)"
                    )

            except ImportError:
                logger.warning("IBM MQ library not available, JMS support disabled")
            except Exception as e:
                logger.warning(f"Failed to initialize JMS: {e}")
        else:
            logger.info("No queue managers configured in queue-managers.yaml")

        # Initialize message cache for tests and rules
        message_cache = MessageCache(ttl_seconds=120, cleanup_interval_seconds=30)
        message_cache.start_cleanup()

        # Initialize results database
        results_db_path = os.getenv("RESULTS_DB_PATH", "/tmp/kafka-wiremock-results.db")
        results_db = ResultsDatabase(db_path=results_db_path)

        # Initialize topic metadata manager
        from .kafka.topic_metadata import TopicMetadataManager
        topic_metadata_manager = TopicMetadataManager(
            config_dir=config_dir,
            test_suite_dir=test_suite_dir,
            kafka_client=kafka_client,
            scan_interval=5,
            topic_check_interval=10
        )

        # Initialize schema registry
        schema_registry_url = os.getenv("SCHEMA_REGISTRY_URL", None)
        from .kafka.schema_registry import SchemaRegistry
        schema_registry = SchemaRegistry(registry_url=schema_registry_url, cache_ttl_seconds=3600)

        listener_engine = KafkaListenerEngine(
            config_loader,
            kafka_client,
            bootstrap_servers,
            custom_placeholder_registry=custom_placeholder_registry,
            message_cache=message_cache,
            topic_metadata_manager=topic_metadata_manager,
            schema_registry=schema_registry,
            http_executor=http_executor  # wired after creation below
        )
         # Start listener engines
        listener_engine.start()

        # Start JMS listener if we have queue managers configured
        if not jms_registry.is_empty():  # NEW: check registry instead of single client
            try:
                from .jms.listener import JMSListenerEngine

                jms_listener_engine = JMSListenerEngine(
                    jms_registry=jms_registry,
                    config_loader=config_loader,
                    jms_config_loader=jms_config_loader,
                    kafka_client=kafka_client,  # needed for msg_type=kafka rule outputs
                    message_cache=message_cache,
                    custom_placeholder_registry=custom_placeholder_registry,
                    http_executor=http_executor  # wired after creation below
                )
                jms_listener_engine.start()
                logger.info("JMS Listener started")
            except Exception as e:
                logger.warning(f"Failed to start JMS listener: {e}")

        # Initialize test suite components
        test_loader = TestLoader(test_suite_dir=test_suite_dir)

        # Initialise HttpExecutor (uses config/http-config/tls.yaml + auth.yaml)
        http_executor = HttpExecutor(config_dir=config_dir)
        # Back-wire into already-created listener engines
        listener_engine.http_executor = http_executor
        if jms_listener_engine is not None:
            jms_listener_engine.http_executor = http_executor

        # Initialise DB components (optional — skipped if databases.yaml absent)
        try:
            from .db.config_loader import DBConfigLoader
            from .db.registry import DBRegistry
            from .db.pool import DBConnectionPool, DBPoolConfig
            from .db.providers.factory import DBProviderFactory
            from .db.executor import DBExecutor

            db_config_dir = os.getenv("DB_CONFIG_DIR", f"{config_dir}/db-config")
            db_provider_dir = os.getenv("DB_PROVIDER_DIR", f"{config_dir}/db_provider")
            db_config_loader = DBConfigLoader(
                config_dir=db_config_dir,
                provider_dir=db_provider_dir,
                scan_interval=30,
            )
            # Load external provider files before creating DB instances
            db_config_loader.start_hot_reload()

            db_registry = DBRegistry()
            db_configs = db_config_loader.load()

            for db_name, db_cfg in db_configs.items():
                try:
                    provider_cfg = db_cfg.to_provider_config()
                    provider = DBProviderFactory.create(db_cfg.provider, provider_cfg)

                    def _make_factory(p=provider):
                        def factory():
                            if not p.is_connected():
                                p.connect()
                            return p
                        return factory

                    pool = DBConnectionPool(
                        provider_factory=_make_factory(),
                        config=db_cfg.pool,
                        db_name=db_name,
                    )
                    # Redact password from stored config
                    safe_cfg = {k: v for k, v in provider_cfg.items() if k != "password"}
                    safe_cfg["provider"] = db_cfg.provider
                    db_registry.add_database(db_name, pool, config=safe_cfg)
                    logger.info(f"Registered DB: '{db_name}' (provider={db_cfg.provider})")
                except Exception as e:
                    logger.warning(
                        f"Failed to initialise DB '{db_name}': {e}. "
                        f"This database will be unavailable."
                    )

            # Create shared DBExecutor — always created when registry exists,
            # even if no pools are up yet (providers connect lazily on first query).
            db_executor_instance = DBExecutor(db_registry)

            if not db_registry.is_empty():
                logger.info(
                    f"Initialised {len(db_registry.get_all_names())} database(s): "
                    f"{', '.join(db_registry.get_all_names())}"
                )
                # Wire db_registry into listener engine
                listener_engine.db_registry = db_registry
            else:
                logger.info("No databases configured (db-config/databases.yaml absent or empty)")
        except Exception as e:
            logger.warning(f"DB subsystem initialisation failed: {e}")
            # Still create a registry and executor so DB actions report a proper
            # error at runtime rather than silently being skipped.
            if db_registry is None:
                from .db.registry import DBRegistry as _DBR
                db_registry = _DBR()
            from .db.executor import DBExecutor as _DBE
            db_executor_instance = _DBE(db_registry)

        # Initialize HTTP Mock Servers (http-config/mock-servers/*.yaml)
        http_stub_cache = HttpStubCache()
        mock_server_config_loader = MockServerConfigLoader(config_dir=config_dir)
        mock_server_configs = mock_server_config_loader.load()
        if mock_server_configs:
            mock_dispatch_handler = MockDispatchHandler(
                config_loader=config_loader,
                server_configs=mock_server_configs,
                stub_cache=http_stub_cache,
                kafka_client=kafka_client,
                jms_registry=jms_registry,
                http_executor=http_executor,
            )
            mock_server_registry = HttpMockServerRegistry()
            for srv_name, srv_config in mock_server_configs.items():
                srv = HttpMockServer(config=srv_config, dispatch_handler=mock_dispatch_handler)
                mock_server_registry.add_server(srv)
            mock_server_registry.start_all()
            logger.info(f"Started {len(mock_server_configs)} HTTP mock server(s)")
        else:
            logger.info("No HTTP mock servers configured (http-config/mock-servers/ is empty or absent)")

        # Pass listener_engine, message_cache, jms_registry, http_executor, stub_cache and db_executor to test suite runner
        test_suite_runner = TestSuiteRunner(
            kafka_client,
            custom_placeholder_registry,
            test_suite_dir,
            message_cache=message_cache,
            listener_engine=listener_engine,
            jms_registry=jms_registry,
            http_executor=http_executor,
            stub_cache=http_stub_cache,
            db_executor=db_executor_instance,
        )
        test_job_manager = TestJobManager()

        # Initialize test listener manager (scans test files and pre-starts listeners)
        test_listener_manager = TestListenerManager(
            listener_engine=listener_engine,
            test_loader=test_loader,
            scan_interval=5
        )
        test_listener_manager.start()

        # Initialize send components
        send_dir = os.getenv("SEND_DIR", "/send")
        send_loader = SendLoader(send_dir=send_dir)
        send_executor = SendExecutor(
            kafka_client,
            custom_placeholder_registry,
            send_dir=send_dir,
            jms_registry=jms_registry,
            http_executor=http_executor,  # NEW: HTTP support in sends
            db_executor=db_executor_instance,  # NEW: DB support in sends
        )

        # Set references in API modules
        kafka_injection.set_kafka_client(kafka_client)
        kafka_injection.set_message_cache(message_cache)
        if not jms_registry.is_empty():  # NEW: pass registry instead of client
            kafka_injection.set_jms_registry(jms_registry)
            kafka_injection.set_jms_config_loader(jms_config_loader)  # NEW
        kafka_injection.set_config_loader(config_loader)
        rules.set_config_loader(config_loader)
        rules.set_listener_engine(listener_engine)
        custom_placeholders.set_custom_placeholder_registry(custom_placeholder_registry)
        dependencies_mgmt.set_dependency_manager(dependency_manager)
        app_settings.set_app_settings_loader(app_settings_loader)
        config.set_topic_config_loader(config_loader.topic_config_loader)  # NEW: config API
        config.set_jms_registry(jms_registry)  # NEW: config API
        jms_api.set_jms_listener_engine(jms_listener_engine)  # JMS listener control API
        discovery.set_test_loader(test_loader)
        execution.set_test_loader(test_loader)
        execution.set_test_suite_runner(test_suite_runner)
        execution.set_test_job_manager(test_job_manager)
        jobs.set_test_job_manager(test_job_manager)
        send_discovery.set_send_loader(send_loader)
        send_execution.set_send_loader(send_loader)
        send_execution.set_send_executor(send_executor)
        decode.set_listener_engine(listener_engine)
        match.set_config_loader(config_loader)
        topics.set_listener_engine(listener_engine)
        topics.set_message_cache(message_cache)
        cache.set_message_cache(message_cache)
        bulk.set_test_loader(test_loader)
        bulk.set_test_suite_runner(test_suite_runner)
        bulk.set_results_db(results_db)
        load_tests.set_test_loader(test_loader)
        load_tests.set_test_suite_runner(test_suite_runner)
        send_bulk.set_send_loader(send_loader)
        send_bulk.set_send_executor(send_executor)
        send_bulk.set_results_db(results_db)
        results.set_results_db(results_db)
        db_api.set_db_registry(db_registry)

        logger.info("Kafka Wiremock started successfully")
    except Exception as e:
        logger.error(f"Failed to start Kafka Wiremock: {e}")
        raise
    yield
    # Shutdown
    logger.info("Shutting down Kafka Wiremock...")
    try:
        if app_settings_loader:
            app_settings_loader.stop()
        if test_listener_manager:
            test_listener_manager.stop()
        if message_cache:
            message_cache.stop_cleanup()
        if dependency_manager:
            dependency_manager.stop()
        if listener_engine:
            listener_engine.stop()
        if jms_listener_engine:
            jms_listener_engine.stop()
        if kafka_client:
            kafka_client.close()
        if jms_registry:  # NEW: close all clients in registry
            jms_registry.close_all()
        if mock_server_registry:
            mock_server_registry.stop_all()
        if db_config_loader:
            db_config_loader.stop()
        if db_registry:
            db_registry.close_all()
        logger.info("Kafka Wiremock shutdown successfully")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


# Create FastAPI app
app = FastAPI(
    title="Kafka Wiremock",
    description="Event-driven Kafka mock container for testing",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update this to specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all API routers FIRST (so they take precedence over static files)
# NOTE: Order matters! More specific routes should come before parametric routes
# All routers are included with /api prefix for unified API namespace
app.include_router(health.router, prefix="/api")
app.include_router(app_settings.router, prefix="/api")
app.include_router(config.router, prefix="/api")  # NEW: configuration viewer
app.include_router(jms_api.router, prefix="/api")  # JMS listener control
app.include_router(kafka_injection.router, prefix="/api")
app.include_router(rules.router, prefix="/api")
app.include_router(custom_placeholders.router, prefix="/api")
app.include_router(dependencies_mgmt.router, prefix="/api")
app.include_router(logs.router, prefix="/api")  # Include BEFORE discovery (logs is more specific than /{test_id})
app.include_router(jobs.router, prefix="/api")  # Include BEFORE discovery
app.include_router(discovery.router, prefix="/api")  # Parametric route, include after specific routes
app.include_router(execution.router, prefix="/api")
app.include_router(send_discovery.router, prefix="/api")
app.include_router(send_execution.router, prefix="/api")
app.include_router(bulk.router, prefix="/api")
app.include_router(load_tests.router, prefix="/api")
app.include_router(send_bulk.router, prefix="/api")
app.include_router(decode.router, prefix="/api")
app.include_router(match.router, prefix="/api")
app.include_router(topics.router, prefix="/api")
app.include_router(cache.router, prefix="/api")
app.include_router(template.router, prefix="/api")
app.include_router(results.router, prefix="/api")
app.include_router(db_api.router, prefix="/api")

# ...existing code...

# Setup static file serving for frontend
# The frontend is built into src/static by the Docker build
static_dir = os.path.join(os.path.dirname(__file__), "static")

# Serve root index.html
@app.get("/", response_class=FileResponse)
async def root():
    """Serve frontend index.html"""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, media_type="text/html")
    return {"message": "Kafka Wiremock API - Navigate to /docs for API documentation"}

# Catch-all for SPA routes - serve index.html for any unmatched path that doesn't look like an API call
@app.api_route("/{path:path}", methods=["GET", "HEAD"], response_class=FileResponse)
async def spa_fallback(path: str):
    """
    Fallback route for SPA - serves static files or index.html for unknown routes.
    This allows Angular routing to work properly.
    Does NOT interfere with API endpoints (all under /api/ prefix).
    """
    # API routes are all under /api/ prefix and should not reach here
    # (they're handled by FastAPI routers registered before this catch-all)
    # If an API route does reach here, it was legitimately not found
    if path.startswith("api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "Not Found"}
        )

    file_path = os.path.join(static_dir, path)

    # Check if it's a static file that exists
    if os.path.isfile(file_path) and os.path.exists(file_path):
        # Determine media type based on file extension
        if path.endswith(".js"):
            media_type = "application/javascript"
        elif path.endswith(".css"):
            media_type = "text/css"
        elif path.endswith(".ico"):
            media_type = "image/x-icon"
        elif path.endswith(".json"):
            media_type = "application/json"
        else:
            media_type = "text/plain"
        return FileResponse(file_path, media_type=media_type)

    # For unknown routes, serve index.html (SPA routing)
    # This allows Angular Router to handle the navigation client-side
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, media_type="text/html")

    return JSONResponse(
        status_code=404,
        content={"detail": "Not Found"}
    )


