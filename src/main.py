"""
FastAPI application for Kafka Wiremock.
"""
import logging
import json
import os
import uuid
from typing import Optional, Dict, Any, List, Union
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header, Query, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from .config_loader import ConfigLoader
from .kafka_client import KafkaClientWrapper
from .kafka_listener import KafkaListenerEngine
from .custom_placeholders import CustomPlaceholderRegistry
from .templater import set_custom_placeholder_registry
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup and shutdown."""
    global config_loader, kafka_client, listener_engine, custom_placeholder_registry
    # Startup
    logger.info("Starting Kafka Wiremock...")
    try:
        # Get Kafka bootstrap servers from environment
        bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        config_dir = os.getenv("CONFIG_DIR", "/config")
        custom_placeholders_dir = os.getenv("CUSTOM_PLACEHOLDERS_DIR", "/config/custom_placeholders")

        # Initialize custom placeholder registry
        custom_placeholder_registry = CustomPlaceholderRegistry(config_dir=custom_placeholders_dir)
        set_custom_placeholder_registry(custom_placeholder_registry)

        # Initialize components
        config_loader = ConfigLoader(config_dir=config_dir, reload_interval=30)
        kafka_client = KafkaClientWrapper(bootstrap_servers=bootstrap_servers)
        listener_engine = KafkaListenerEngine(
            config_loader,
            kafka_client,
            bootstrap_servers,
            custom_placeholder_registry=custom_placeholder_registry
        )
        # Start listener engine
        listener_engine.start()
        logger.info("Kafka Wiremock started successfully")
    except Exception as e:
        logger.error(f"Failed to start Kafka Wiremock: {e}")
        raise
    yield
    # Shutdown
    logger.info("Shutting down Kafka Wiremock...")
    try:
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
) -> List[ConsumedMessage]:
    """
    Retrieve messages from a Kafka topic.
    Args:
        topic: Kafka topic to consume from
        limit: Maximum number of messages to retrieve (default: 10, max: 100)
    Returns:
        List of consumed messages
    """
    if not kafka_client:
        raise HTTPException(status_code=503, detail="Kafka client not initialized")
    try:
        # Consume latest messages
        messages = kafka_client.consume_latest(topic=topic, max_messages=limit)
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
async def get_rules():
    """
    Get all configured rules.
    Returns:
        List of rules with details
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
        return result
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
