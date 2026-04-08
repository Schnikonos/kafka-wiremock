"""
Health check endpoint for Kafka Wiremock.
"""
import logging
from fastapi import APIRouter
from .models import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="ok")

