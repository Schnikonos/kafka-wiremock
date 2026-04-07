"""
FastAPI application for Kafka Wiremock.
"""
import logging
import json
import os
import uuid
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header, Query, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from .config.loader import ConfigLoader
from .kafka.client import KafkaClientWrapper
from .kafka.listener import KafkaListenerEngine
from .custom.placeholders import CustomPlaceholderRegistry
from .rules.templater import set_custom_placeholder_registry
from .test.loader import TestLoader, TestInjection, TestExpectation, TestScript
from .test.suite import TestSuiteRunner, TestResultAggregator
from .test.jobs import TestJobManager
from .test.cache import MessageCache
from .test.listener_manager import TestListenerManager
from .dependencies.manager import DependencyManager
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# Request/Response models
class InjectMessageRequest(BaseModel):
    """Request body for injecting a message."""
    message: Union[Dict[str, Any], str]
    schema_id: Optional[int] = None
class InjectMessageResponse(BaseModel):
    """Response for injected message."""
    message_id: str
    topic: str
    status: str = "success"
class ConsumedMessage(BaseModel):
    """A consumed message from Kafka."""
    timestamp: int
    partition: int
    offset: int
    key: Optional[str] = None
    value: Any
    format: str
class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
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
        config_loader = ConfigLoader(config_dir=config_dir, reload_interval=30)
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
            scan_interval=30,
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
            scan_interval=30
        )
        test_listener_manager.start()

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
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="ok")
@app.post("/inject/{topic}", response_model=InjectMessageResponse)
async def inject_message(
    topic: str,
    request: InjectMessageRequest,
    schema_id: Optional[int] = Header(None, alias="schema-id"),
) -> InjectMessageResponse:
    """
    Inject a message into a Kafka topic.
    Args:
        topic: Target Kafka topic
        request: Message and optional schema info
        schema_id: Optional schema ID header for AVRO
    Returns:
        InjectMessageResponse with message ID
    """
    if not kafka_client:
        raise HTTPException(status_code=503, detail="Kafka client not initialized")
    try:
        # Get message from request
        message = request.message
        if message is None:
            raise HTTPException(status_code=400, detail="Message is required")
        # Produce to Kafka
        message_id = kafka_client.produce(
            topic=topic,
            message=message,
            schema_id=schema_id
        )
        if message_id is None:
            raise HTTPException(status_code=500, detail="Failed to produce message to Kafka")
        return InjectMessageResponse(
            message_id=message_id,
            topic=topic,
            status="success"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error injecting message to {topic}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/messages/{topic}", response_model=List[ConsumedMessage])
async def get_messages(
    topic: str,
    limit: int = Query(10, ge=1, le=100),
    timeout_ms: int = Query(500, ge=1, le=30000, description="Total polling timeout in milliseconds (default: 500)"),
    poll_interval_ms: int = Query(100, ge=1, le=5000, description="Individual poll interval in milliseconds (default: 100)"),
) -> List[ConsumedMessage]:
    """
    Retrieve messages from a Kafka topic.
    Args:
        topic: Kafka topic to consume from
        limit: Maximum number of messages to retrieve (default: 10, max: 100)
        timeout_ms: Total time budget for polling in milliseconds (default: 500)
        poll_interval_ms: Duration of each individual poll in milliseconds (default: 100)
    Returns:
        List of consumed messages
    """
    if not kafka_client:
        raise HTTPException(status_code=503, detail="Kafka client not initialized")
    try:
        # Consume latest messages
        messages = kafka_client.consume_latest(topic=topic, max_messages=limit,
                                               timeout_ms=timeout_ms, poll_interval_ms=poll_interval_ms)
        # Convert to response format
        result = []
        for msg in messages:
            if "error" not in msg:
                result.append(ConsumedMessage(**msg))
        return result
    except Exception as e:
        logger.error(f"Error consuming messages from {topic}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/rules")
async def get_rules(errors: bool = Query(False, description="If true, include validation errors")):
    """
    Get all configured rules.

    Args:
        errors: If true, include validation errors for all rule files

    Returns:
        List of rules with details, optionally including validation errors
    """
    if not config_loader:
        raise HTTPException(status_code=503, detail="Config loader not initialized")
    try:
        rules = config_loader.get_all_rules()
        result = []
        for rule in rules:
            outputs = [
                {
                    "topic": output.topic,
                    "payload": output.payload,
                    "delay_ms": output.delay_ms,
                    "headers": output.headers,
                    "schema_id": output.schema_id
                }
                for output in rule.outputs
            ]
            conditions = [
                {
                    "type": cond.type,
                    "expression": cond.expression,
                    "value": cond.value,
                    "regex": cond.regex
                }
                for cond in rule.conditions
            ]
            result.append({
                "name": rule.rule_name,
                "priority": rule.priority,
                "conditions": conditions,
                "input_topic": rule.input_topic,
                "outputs": outputs,
            })

        response = {"rules": result}

        # Add validation errors if requested
        if errors:
            response["validation_errors"] = config_loader.validation_errors or {}
            response["has_errors"] = bool(config_loader.validation_errors)

        return response
    except Exception as e:
        logger.error(f"Error retrieving rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/rules/{input_topic}")
async def get_rules_for_topic(input_topic: str):
    """
    Get rules for a specific input topic.
    Args:
        input_topic: Input topic name
    Returns:
        Rules that apply to this topic
    """
    if not config_loader:
        raise HTTPException(status_code=503, detail="Config loader not initialized")
    try:
        rules = config_loader.get_rules_for_topic(input_topic)
        result = []
        for rule in rules:
            outputs = [
                {
                    "topic": output.topic,
                    "payload": output.payload,
                    "delay_ms": output.delay_ms,
                    "headers": output.headers,
                    "schema_id": output.schema_id
                }
                for output in rule.outputs
            ]
            conditions = [
                {
                    "type": cond.type,
                    "expression": cond.expression,
                    "value": cond.value,
                    "regex": cond.regex
                }
                for cond in rule.conditions
            ]
            result.append({
                "name": rule.rule_name,
                "priority": rule.priority,
                "conditions": conditions,
                "input_topic": rule.input_topic,
                "outputs": outputs,
            })
        return result
    except Exception as e:
        logger.error(f"Error retrieving rules for topic {input_topic}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/custom-placeholders")
async def get_custom_placeholders():
    """
    Get all custom placeholders with their metadata.

    Returns:
        List of custom placeholders with execution order
    """
    if not custom_placeholder_registry:
        raise HTTPException(status_code=503, detail="Custom placeholder registry not initialized")

    try:
        placeholders = custom_placeholder_registry.get_all_placeholders()
        order_map = custom_placeholder_registry.placeholder_order

        result = []
        for name, func in placeholders.items():
            order_priority = order_map.get(name)
            result.append({
                "name": name,
                "order": order_priority,
                "docstring": func.__doc__ or ""
            })

        # Sort by execution order
        result.sort(key=lambda x: (x["order"] is not None, x["order"] or 0))

        return result
    except Exception as e:
        logger.error(f"Error retrieving custom placeholders: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dependencies")
async def get_dependency_status() -> Dict[str, Any]:
    """
    Get status of Python dependency manager.

    Returns:
        Dependency status, requirements.txt existence, and last installation info
    """
    if not dependency_manager:
        raise HTTPException(status_code=503, detail="Dependency manager not initialized")

    try:
        requirements_exists = dependency_manager.requirements_file.exists()
        log_exists = dependency_manager.log_file.exists()
        
        result = {
            "status": "running" if dependency_manager._running else "stopped",
            "requirements_file": str(dependency_manager.requirements_file),
            "requirements_exists": requirements_exists,
            "log_file": str(dependency_manager.log_file),
            "log_exists": log_exists,
            "scan_interval_seconds": dependency_manager.scan_interval
        }
        
        # Include last few lines of log if it exists
        if log_exists:
            try:
                with open(dependency_manager.log_file, 'r') as f:
                    log_content = f.read()
                    result["last_installation_log"] = log_content
            except Exception as e:
                logger.warning(f"Failed to read dependency log: {e}")
        
        return result
    except Exception as e:
        logger.error(f"Error retrieving dependency status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Test Suite Endpoints
# ============================================================================

@app.get("/tests")
async def list_tests(errors: bool = Query(False, description="If true, include validation errors")) -> Dict[str, Any]:
    """
    List all discovered test definitions.

    Args:
        errors: If true, include validation errors for all test files

    Returns:
        Dictionary with test metadata, optionally including validation errors
    """
    if not test_loader:
        raise HTTPException(status_code=503, detail="Test loader not initialized")

    try:
        tests = test_loader.discover_tests()
        result = []
        for test in tests:
            when_injections = sum(1 for item in test.when.items if isinstance(item, TestInjection))
            then_expectations = sum(1 for item in test.then.items if isinstance(item, TestExpectation))
            result.append({
                "test_id": test.name,
                "priority": test.priority,
                "tags": test.tags,
                "skip": test.skip,
                "timeout_ms": test.timeout_ms,
                "when_injections": when_injections,
                "then_expectations": then_expectations
            })

        response = {
            "total": len(result),
            "tests": result
        }

        # Add validation errors if requested
        if errors:
            response["validation_errors"] = test_loader.validation_errors or {}
            response["has_errors"] = bool(test_loader.validation_errors)

        return response
    except Exception as e:
        logger.error(f"Error listing tests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tests/{test_id}")
async def get_test_definition(test_id: str) -> Dict[str, Any]:
    """
    Get parsed test definition.
    Args:
        test_id: Test identifier (from test name)
    Returns:
        Test definition as dictionary
    """
    if not test_loader:
        raise HTTPException(status_code=503, detail="Test loader not initialized")

    try:
        tests = test_loader.discover_tests()
        test = next((t for t in tests if t.name == test_id), None)
        if not test:
            raise HTTPException(status_code=404, detail=f"Test not found: {test_id}")

        return {
            "name": test.name,
            "priority": test.priority,
            "tags": test.tags,
            "skip": test.skip,
            "timeout_ms": test.timeout_ms,
            "when": {
                "injections": [
                    {
                        "message_id": inj.message_id,
                        "topic": inj.topic,
                        "delay_ms": inj.delay_ms
                    }
                    for inj in test.when.items if isinstance(inj, TestInjection)
                ],
                "has_script": any(isinstance(item, TestScript) for item in test.when.items)
            },
            "then": {
                "expectations": [
                    {
                        "topic": exp.topic,
                        "source_id": exp.source_id,
                        "target_id": exp.target_id,
                        "wait_ms": exp.wait_ms,
                        "conditions_count": len(exp.match)
                    }
                    for exp in test.then.items if isinstance(exp, TestExpectation)
                ],
                "has_script": any(isinstance(item, TestScript) for item in test.then.items)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tests/{test_id}")
async def run_single_test(
    test_id: str,
    async_mode: bool = Query(False, description="If true, run asynchronously and return job_id"),
    verbose: bool = Query(False, description="If true, include received_messages and skipped_messages in logs")
) -> Dict[str, Any]:
    """
    Run a single test by ID.

    Args:
        test_id: Test identifier
        async_mode: If true, returns immediately with job_id (202 Accepted)
        verbose: If true, include detailed message logs in test output

    Returns:
        If async_mode: {job_id, status, created_at}
        If sync_mode: Full test result
    """
    if not test_loader or not test_suite_runner or not test_job_manager:
        raise HTTPException(status_code=503, detail="Test suite not initialized")

    try:
        tests = test_loader.discover_tests()
        test = next((t for t in tests if t.name == test_id), None)
        if not test:
            raise HTTPException(status_code=404, detail=f"Test not found: {test_id}")

        if async_mode:
            # Create async job
            job_id = test_job_manager.create_job(test_id)
            test_job_manager.start_job(job_id)

            # Run test in background
            import asyncio
            asyncio.create_task(
                _run_test_async(job_id, test, test_job_manager, test_suite_runner, test_loader, test_job_manager.list_jobs, verbose)
            )

            # Return 202 Accepted with job info
            return {
                "job_id": job_id,
                "status": "RUNNING",
                "created_at": test_job_manager.get_job(job_id).created_at,
                "message": "Test running asynchronously. Use GET /tests/jobs/{job_id} to poll status."
            }
        else:
            # Synchronous execution (current behavior)
            # Use file_path stored in test definition
            test_file_path = Path(test.file_path) if test.file_path else None

            result = await test_suite_runner.executor.run_test(test, test_file_path, verbose=verbose)

            # Convert result to JSON-serializable dict
            return {
                "test_id": result.test_id,
                "status": result.status,
                "elapsed_ms": result.elapsed_ms,
                "when_result": {
                    "injected": result.when_result.injected,
                    "script_error": result.when_result.script_error
                },
                "then_result": {
                    "expectations": [
                        {
                            "index": exp.index,
                            "topic": exp.topic,
                            "expected": exp.expected,
                            "received": exp.received,
                            "status": exp.status,
                            "elapsed_ms": exp.elapsed_ms,
                            "error": exp.error
                        }
                        for exp in result.then_result.expectations
                    ],
                    "script_error": result.then_result.script_error
                },
                "errors": result.errors
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _run_test_async(
    job_id: str,
    test,
    job_manager,
    suite_runner,
    loader,
    list_jobs_fn,
    verbose: bool = False
):
    """Helper to run test asynchronously and update job status."""
    try:
        # Use file_path stored in test definition
        test_file_path = Path(test.file_path) if test.file_path else None

        result = await suite_runner.executor.run_test(test, test_file_path, verbose=verbose)

        # Convert to dict
        result_dict = {
            "test_id": result.test_id,
            "status": result.status,
            "elapsed_ms": result.elapsed_ms,
            "when_result": {
                "injected": result.when_result.injected,
                "script_error": result.when_result.script_error
            },
            "then_result": {
                "expectations": [
                    {
                        "index": exp.index,
                        "topic": exp.topic,
                        "expected": exp.expected,
                        "received": exp.received,
                        "status": exp.status,
                        "elapsed_ms": exp.elapsed_ms,
                        "error": exp.error
                    }
                    for exp in result.then_result.expectations
                ],
                "script_error": result.then_result.script_error
            },
            "errors": result.errors
        }

        job_manager.complete_job(job_id, result_dict)
    except Exception as e:
        logger.error(f"Async test {job_id} failed: {e}")
        job_manager.fail_job(job_id, str(e))


@app.post("/tests:bulk")
async def run_tests_bulk(
    mode: str = Query("parallel", description="sequential or parallel"),
    threads: int = Query(4, ge=1, le=32, description="Number of concurrent threads (for parallel mode)"),
    iterations: int = Query(1, ge=1, le=1000, description="Number of iterations per test"),
    filter_tags: Optional[List[str]] = Query(None, description="Optional tags to filter tests"),
    verbose: bool = Query(False, description="If true, include received_messages and skipped_messages in logs")
) -> Dict[str, Any]:
    """
    Run all discovered tests in bulk.
    Args:
        mode: Execution mode (sequential or parallel)
        threads: Number of concurrent threads
        iterations: Number of iterations per test
        filter_tags: Optional tags to filter tests
        verbose: If true, include detailed message logs in test output
    Returns:
        Aggregated test results
    """
    if not test_loader or not test_suite_runner:
        raise HTTPException(status_code=503, detail="Test suite not initialized")

    try:
        if mode not in ["sequential", "parallel"]:
            raise HTTPException(status_code=400, detail="mode must be 'sequential' or 'parallel'")

        # Discover tests
        all_tests = test_loader.discover_tests()

        # Filter by tags if specified
        if filter_tags:
            all_tests = test_loader.get_tests_by_tag(all_tests, filter_tags)

        if not all_tests:
            raise HTTPException(status_code=400, detail="No tests found matching criteria")

        # Replicate tests for iterations
        tests_to_run = all_tests * iterations

        logger.info(f"Running {len(tests_to_run)} test instances ({len(all_tests)} tests × {iterations} iterations) in {mode} mode (verbose={verbose})")

        # Run tests
        if mode == "sequential":
            results = await test_suite_runner.run_tests_sequential(tests_to_run, verbose=verbose)
        else:  # parallel
            results = await test_suite_runner.run_tests_parallel(tests_to_run, threads=threads, verbose=verbose)

        # Aggregate results
        aggregated = TestResultAggregator.aggregate_results(results, mode=mode)

        return aggregated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running bulk tests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tests/jobs/{job_id}")
async def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get status of an async test job.

    Args:
        job_id: Job ID returned from async test POST

    Returns:
        Job status, progress, and result if completed
    """
    if not test_job_manager:
        raise HTTPException(status_code=503, detail="Job manager not initialized")

    try:
        job = test_job_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

        response = job.to_dict()

        # If job is complete, clean it up on next access
        if job.status.value in ["COMPLETED", "FAILED", "CANCELLED"]:
            # Mark for cleanup but return the result first
            pass

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tests/logs")
async def list_test_logs() -> Dict[str, Any]:
    """
    List all test log files.

    Returns:
        Dictionary with log files and their content
    """
    try:
        test_suite_dir = Path(os.getenv("TEST_SUITE_DIR", "/testSuite"))

        # Find all .test.log files recursively
        log_files = sorted(test_suite_dir.rglob("*.test.log"))

        if not log_files:
            return {
                "total": 0,
                "logs": [],
                "test_suite_dir": str(test_suite_dir),
                "test_suite_exists": test_suite_dir.exists()
            }

        logs = []
        for log_file in log_files:
            try:
                with open(log_file, 'r') as f:
                    content = f.read()
                logs.append({
                    "path": str(log_file),
                    "relative_path": str(log_file.relative_to(test_suite_dir)),
                    "size_bytes": log_file.stat().st_size,
                    "modified": log_file.stat().st_mtime,
                    "content_preview": content[:500] + ("..." if len(content) > 500 else "")
                })
            except Exception as e:
                logger.error(f"Failed to read log file {log_file}: {e}")
                logs.append({
                    "path": str(log_file),
                    "error": str(e)
                })

        return {
            "total": len(logs),
            "logs": logs,
            "test_suite_dir": str(test_suite_dir)
        }
    except Exception as e:
        logger.error(f"Error listing test logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tests/logs/{test_id}")
async def get_test_log(test_id: str) -> Dict[str, Any]:
    """
    Get the log file content for a specific test.

    Args:
        test_id: Test identifier (uses the test name to find the log)

    Returns:
        Full log file content
    """
    try:
        test_suite_dir = Path(os.getenv("TEST_SUITE_DIR", "/testSuite"))

        # Search for log file matching the test ID
        log_files = list(test_suite_dir.rglob("*.test.log"))

        matching_logs = [
            lf for lf in log_files
            if test_id in lf.name or test_id in lf.read_text()
        ]

        if not matching_logs:
            raise HTTPException(
                status_code=404,
                detail=f"No log file found for test '{test_id}'"
            )

        log_file = matching_logs[0]

        with open(log_file, 'r') as f:
            content = f.read()

        return {
            "test_id": test_id,
            "log_path": str(log_file),
            "log_size_bytes": log_file.stat().st_size,
            "content": content
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving log for test {test_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tests/jobs")
async def list_jobs(test_id: Optional[str] = Query(None, description="Filter by test ID")) -> Dict[str, Any]:
    """
    List all running/completed jobs.

    Args:
        test_id: Optional test ID to filter by

    Returns:
        List of jobs with their status
    """
    if not test_job_manager:
        raise HTTPException(status_code=503, detail="Job manager not initialized")

    try:
        jobs = test_job_manager.list_jobs(test_id)
        return {
            "total": len(jobs),
            "jobs": jobs
        }
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/rules:match")
async def explain_rule_match(
    topic: str = Query(..., description="Input topic"),
    message: Union[Dict[str, Any], str] = Body(..., description="Message to test against rules")
) -> Dict[str, Any]:
    """
    Dry-run endpoint: Show which rule would match a message and why.

    Args:
        topic: Input topic for the message
        message: Message payload (JSON object or string)

    Returns:
        Matching rule details with matcher context and extraction results
    """
    if not config_loader or not listener_engine:
        raise HTTPException(status_code=503, detail="Services not initialized")

    try:
        # Get rules for the topic
        rules = config_loader.get_rules_for_topic(topic)

        if not rules:
            return {
                "matched": False,
                "message": "No rules configured for this topic",
                "message_preview": str(message)[:200],
                "topic": topic,
                "evaluated_rules": 0
            }

        # Try to match each rule
        for rule in rules:
            match_result = listener_engine.matcher_factory.match_rule(
                message=message,
                rule=rule
            )

            if match_result.matched:
                # Extract details about what matched
                conditions_detail = []
                for i, cond in enumerate(rule.conditions):
                    cond_match = match_result.context.get(f"condition_{i}")
                    conditions_detail.append({
                        "index": i,
                        "type": cond.type,
                        "expression": cond.expression,
                        "value": cond.value,
                        "regex": cond.regex,
                        "matched": cond_match is not None,
                        "extracted_context": dict(list(match_result.context.items())[i:i+1]) if cond_match else {}
                    })

                return {
                    "matched": True,
                    "rule": {
                        "name": rule.rule_name,
                        "priority": rule.priority,
                        "input_topic": rule.input_topic
                    },
                    "conditions": conditions_detail,
                    "context": match_result.context,
                    "message_preview": str(message)[:200],
                    "topic": topic,
                    "outputs_count": len(rule.outputs),
                    "outputs": [{"topic": o.topic, "delay_ms": o.delay_ms} for o in rule.outputs]
                }

        # No rule matched
        return {
            "matched": False,
            "message": "No rules matched this message",
            "message_preview": str(message)[:200],
            "topic": topic,
            "evaluated_rules": len(rules),
            "available_rules": [
                {
                    "name": r.rule_name,
                    "priority": r.priority,
                    "conditions": len(r.conditions)
                }
                for r in rules
            ]
        }
    except Exception as e:
        logger.error(f"Error explaining rule match: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/templates:render")
async def render_template(
    template: str = Body(..., description="Template string with placeholders"),
    context: Dict[str, Any] = Body({}, description="Context dictionary for placeholder substitution")
) -> Dict[str, Any]:
    """
    Dry-run endpoint: Render a template with provided context.

    Args:
        template: Template string (e.g., '{"id": "{{uuid}}", "now": "{{now}}", "field": "{{$.myField}}"}')
        context: Context dictionary with values to substitute

    Returns:
        Rendered template and available/used placeholders
    """
    try:
        from .rules.templater import TemplateRenderer

        # Render the template
        rendered = TemplateRenderer.render(template, context)

        # Extract placeholders from template to show what was available/used
        import re
        placeholder_pattern = re.compile(r'\{\{[\s]*([a-zA-Z0-9_.$\[\](),\-+]+)[\s]*\}\}')
        found_placeholders = placeholder_pattern.findall(template)

        return {
            "success": True,
            "template": template,
            "rendered": rendered,
            "placeholders_found": found_placeholders,
            "context_keys": list(context.keys()),
            "template_length": len(template),
            "rendered_length": len(rendered)
        }
    except Exception as e:
        logger.error(f"Error rendering template: {e}")
        return {
            "success": False,
            "error": str(e),
            "template": template
        }


@app.post("/debug/decode")
async def debug_decode(
    topic: str = Body(..., description="Kafka topic name"),
    payload: Union[str, bytes] = Body(..., description="Message payload (base64 encoded bytes or JSON/string)")
) -> Dict[str, Any]:
    """
    Debug endpoint: Decode a message and show format detection.
    
    Args:
        topic: Topic name (used to determine expected format from metadata)
        payload: Raw message bytes (base64 encoded) or string/JSON
    
    Returns:
        Decoded message, detected format, and deserialization details
    """
    try:
        if not listener_engine:
            raise HTTPException(status_code=503, detail="Listener engine not initialized")
        
        import base64
        
        # Handle payload encoding
        raw_bytes = None
        if isinstance(payload, str):
            try:
                # Try to decode as base64 first
                raw_bytes = base64.b64decode(payload, validate=True)
            except Exception:
                # Fall back to UTF-8 encoding
                raw_bytes = payload.encode('utf-8')
        else:
            raw_bytes = payload
        
        # Get topic metadata
        topic_type = "json"
        if listener_engine.topic_metadata_manager:
            topic_type = listener_engine.topic_metadata_manager.get_topic_type(topic)
        
        # Deserialize
        decoded, fmt = listener_engine._deserialize_message(
            type('MockMessage', (), {'value': raw_bytes})(),
            topic_type
        )
        
        # Get schema registry info if available
        schema_registry_status = None
        if listener_engine.schema_registry:
            schema_registry_status = listener_engine.schema_registry.get_cache_stats()
        
        return {
            "success": True,
            "topic": topic,
            "expected_format": topic_type,
            "detected_format": fmt,
            "decoded_value": decoded,
            "payload_size_bytes": len(raw_bytes),
            "schema_registry": schema_registry_status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in debug decode: {e}")
        return {
            "success": False,
            "error": str(e),
            "topic": topic,
            "payload_size_bytes": len(raw_bytes) if 'raw_bytes' in locals() else 0
        }


@app.post("/debug/match")
async def debug_match(
    topic: str = Body(..., description="Kafka topic name"),
    payload: Union[str, dict] = Body(..., description="Message payload (JSON)"),
    rule_name: Optional[str] = Body(None, description="Specific rule name to test (optional, tests all if omitted)")
) -> Dict[str, Any]:
    """
    Debug endpoint: Test message matching against rules and show detailed analysis.
    
    Args:
        topic: Topic name
        payload: Message content (as JSON dict or string)
        rule_name: Optional specific rule to test
    
    Returns:
        Detailed matching analysis including which conditions matched/failed
    """
    try:
        if not config_loader:
            raise HTTPException(status_code=503, detail="Config loader not initialized")
        
        # Parse payload if string
        if isinstance(payload, str):
            payload = json.loads(payload)
        
        # Get rules for this topic
        rules = config_loader.get_rules_for_topic(topic)
        
        if not rules:
            return {
                "success": True,
                "topic": topic,
                "message_preview": str(payload)[:200],
                "result": "NO_RULES",
                "message": "No rules configured for this topic",
                "rules_evaluated": 0
            }
        
        # Filter by rule name if specified
        if rule_name:
            rules = [r for r in rules if r.rule_name == rule_name]
            if not rules:
                return {
                    "success": False,
                    "error": f"Rule '{rule_name}' not found",
                    "topic": topic
                }
        
        # Evaluate each rule
        rule_results = []
        first_match = None
        
        for rule in rules:
            # Test each condition
            condition_details = []
            rule_matches = True
            
            if not rule.conditions:
                # Wildcard rule
                rule_matches = True
            else:
                for cond_idx, condition in enumerate(rule.conditions):
                    try:
                        from .rules.matcher import MatcherFactory
                        matcher = MatcherFactory.create(condition.type)
                        
                        if condition.type == 'jsonpath':
                            match_condition = {
                                'path': condition.expression,
                                'value': condition.value,
                                'regex': condition.regex
                            }
                        else:
                            match_condition = condition.regex if condition.regex else condition.value
                        
                        result = matcher.match(payload, match_condition)
                        
                        condition_details.append({
                            "index": cond_idx,
                            "type": condition.type,
                            "expression": condition.expression,
                            "value": condition.value,
                            "regex": condition.regex,
                            "matched": result.matched,
                            "context": result.context
                        })
                        
                        if not result.matched:
                            rule_matches = False
                    
                    except Exception as e:
                        logger.error(f"Error evaluating condition {cond_idx}: {e}")
                        condition_details.append({
                            "index": cond_idx,
                            "error": str(e),
                            "matched": False
                        })
                        rule_matches = False
            
            rule_result = {
                "rule_name": rule.rule_name,
                "priority": rule.priority,
                "matched": rule_matches,
                "conditions": condition_details,
                "conditions_count": len(rule.conditions),
                "outputs_count": len(rule.outputs),
                "output_topics": [o.topic for o in rule.outputs]
            }
            rule_results.append(rule_result)
            
            if rule_matches and first_match is None:
                first_match = rule_result
        
        return {
            "success": True,
            "topic": topic,
            "message_preview": str(payload)[:300],
            "total_rules": len(rules),
            "first_match": first_match,
            "all_rules": rule_results
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in debug match: {e}")
        return {
            "success": False,
            "error": str(e),
            "topic": topic
        }


@app.get("/debug/topics")
async def debug_topics() -> Dict[str, Any]:
    """
    Debug endpoint: Show all discovered topics and their metadata.
    
    Returns:
        List of all topics with their types, existence status, and other metadata
    """
    try:
        if not listener_engine or not listener_engine.topic_metadata_manager:
            return {
                "success": False,
                "message": "Topic metadata manager not available"
            }
        
        summary = listener_engine.topic_metadata_manager.get_metadata_summary()
        
        # Get consumer subscription status
        consumer_subscription = []
        if listener_engine.consumer:
            try:
                consumer_subscription = list(listener_engine.consumer.subscription() or [])
            except Exception as e:
                logger.debug(f"Error getting consumer subscription: {e}")
        
        return {
            "success": True,
            "total_topics": summary["total_topics"],
            "consumer_subscribed": sorted(consumer_subscription),
            "topics": summary["topics"],
            "cache_stats": message_cache.get_cache_stats() if message_cache else None
        }
    
    except Exception as e:
        logger.error(f"Error in debug topics: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@app.get("/debug/cache")
async def debug_cache() -> Dict[str, Any]:
    """
    Debug endpoint: Show message cache statistics and contents.
    
    Returns:
        Cache statistics including message counts, consumption status, and formats
    """
    try:
        if not message_cache:
            raise HTTPException(status_code=503, detail="Message cache not initialized")
        
        return {
            "success": True,
            "cache_stats": message_cache.get_cache_stats(),
            "ttl_seconds": message_cache.ttl_seconds
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in debug cache: {e}")
        return {
            "success": False,
            "error": str(e)
        }


