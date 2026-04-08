"""
Shared Pydantic models for API request/response serialization.
"""
from typing import Optional, Dict, Any
from pydantic import BaseModel


class InjectMessageRequest(BaseModel):
    """Request body for injecting a message."""
    message: dict | str
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

