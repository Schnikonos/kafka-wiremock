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
from .config.loader import ConfigLoader
from .kafka.client import KafkaClientWrapper
from .kafka.listener import KafkaListenerEngine
from .custom.placeholders import CustomPlaceholderRegistry
from .rules.templater import set_custom_placeholder_registry
from .test.loader import TestLoader
from .test.suite import TestSuiteRunner
from .test.jobs import TestJobManager
from .test.cache import MessageCache
from .test.listener_manager import TestListenerManager
from .dependencies.manager import DependencyManager

# Import API routers and setter functions
from .api import health, kafka_injection, rules, custom_placeholders, dependencies_mgmt
from .api.tests import discovery, execution, jobs, logs
from .api.debug import decode, match, topics, cache, template

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
config_loader: Optional[ConfigLoader] = None
kafka_client: Optional[KafkaClientWrapper] = None
listener_engine: Optional[KafkaListenerEngine] = None
custom_placeholder_registry: Optional[CustomPlaceholderRegistry] = None
test_loader: Optional[TestLoader] = None
test_suite_runner: Optional[TestSuiteRunner] = None
test_job_manager: Optional[TestJobManager] = None
dependency_manager: Optional[DependencyManager] = None
message_cache: Optional[MessageCache] = None
test_listener_manager: Optional[TestListenerManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup and shutdown."""
    global config_loader, kafka_client, listener_engine, custom_placeholder_registry, test_loader, test_suite_runner, test_job_manager, dependency_manager, message_cache, test_listener_manager
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

        # Set references in API modules
        kafka_injection.set_kafka_client(kafka_client)
        rules.set_config_loader(config_loader)
        rules.set_listener_engine(listener_engine)
        custom_placeholders.set_custom_placeholder_registry(custom_placeholder_registry)
        dependencies_mgmt.set_dependency_manager(dependency_manager)
        discovery.set_test_loader(test_loader)
        execution.set_test_loader(test_loader)
        execution.set_test_suite_runner(test_suite_runner)
        execution.set_test_job_manager(test_job_manager)
        jobs.set_test_job_manager(test_job_manager)
        decode.set_listener_engine(listener_engine)
        match.set_config_loader(config_loader)
        topics.set_listener_engine(listener_engine)
        topics.set_message_cache(message_cache)
        cache.set_message_cache(message_cache)

        logger.info("Kafka Wiremock started successfully")
    except Exception as e:
        logger.error(f"Failed to start Kafka Wiremock: {e}")
        raise
    yield
    # Shutdown
    logger.info("Shutting down Kafka Wiremock...")
    try:
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

# Include all API routers
app.include_router(health.router)
app.include_router(kafka_injection.router)
app.include_router(rules.router)
app.include_router(custom_placeholders.router)
app.include_router(dependencies_mgmt.router)
app.include_router(discovery.router)
app.include_router(execution.router)
app.include_router(jobs.router)
app.include_router(logs.router)
app.include_router(decode.router)
app.include_router(match.router)
app.include_router(topics.router)
app.include_router(cache.router)
app.include_router(template.router)

