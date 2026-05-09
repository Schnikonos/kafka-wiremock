"""
FastAPI application for Kafka Wiremock.

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

# Import API routers and setter functions
from .api import health, kafka_injection, rules, custom_placeholders, dependencies_mgmt, results, app_settings
from .api.tests import discovery, execution, jobs, logs, bulk
from .api.send import discovery as send_discovery, execution as send_execution, bulk as send_bulk
from .api.debug import decode, match, topics, cache, template

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
config_loader: Optional[ConfigLoader] = None
app_settings_loader: Optional[AppSettingsLoader] = None
kafka_client: Optional[KafkaClientWrapper] = None
listener_engine: Optional[KafkaListenerEngine] = None
custom_placeholder_registry: Optional[CustomPlaceholderRegistry] = None
test_loader: Optional[TestLoader] = None
test_suite_runner: Optional[TestSuiteRunner] = None
test_job_manager: Optional[TestJobManager] = None
dependency_manager: Optional[DependencyManager] = None
message_cache: Optional[MessageCache] = None
test_listener_manager: Optional[TestListenerManager] = None
send_loader: Optional[SendLoader] = None
send_executor: Optional[SendExecutor] = None
results_db: Optional[ResultsDatabase] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup and shutdown."""
    global config_loader, app_settings_loader, kafka_client, listener_engine, custom_placeholder_registry, test_loader, test_suite_runner, test_job_manager, dependency_manager, message_cache, test_listener_manager, send_loader, send_executor, results_db
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

        # Initialize components
        config_loader = ConfigLoader(config_dir=config_dir, reload_interval=5)
        kafka_client = KafkaClientWrapper(bootstrap_servers=bootstrap_servers)

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
            schema_registry=schema_registry
        )
        # Start listener engine
        listener_engine.start()

        # Initialize test suite components
        test_loader = TestLoader(test_suite_dir=test_suite_dir)

        # Pass listener_engine and message_cache to test suite runner
        test_suite_runner = TestSuiteRunner(
            kafka_client,
            custom_placeholder_registry,
            test_suite_dir,
            message_cache=message_cache,
            listener_engine=listener_engine
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
            send_dir=send_dir
        )

        # Set references in API modules
        kafka_injection.set_kafka_client(kafka_client)
        rules.set_config_loader(config_loader)
        rules.set_listener_engine(listener_engine)
        custom_placeholders.set_custom_placeholder_registry(custom_placeholder_registry)
        dependencies_mgmt.set_dependency_manager(dependency_manager)
        app_settings.set_app_settings_loader(app_settings_loader)
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
        send_bulk.set_send_loader(send_loader)
        send_bulk.set_send_executor(send_executor)
        send_bulk.set_results_db(results_db)
        results.set_results_db(results_db)

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
        if kafka_client:
            kafka_client.close()
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
app.include_router(send_bulk.router, prefix="/api")
app.include_router(decode.router, prefix="/api")
app.include_router(match.router, prefix="/api")
app.include_router(topics.router, prefix="/api")
app.include_router(cache.router, prefix="/api")
app.include_router(template.router, prefix="/api")
app.include_router(results.router, prefix="/api")

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


