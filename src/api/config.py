"""
Configuration API endpoints for viewing topic and JMS configurations.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# Global references (set by main.py)
_topic_config_loader = None
_jms_registry = None


def set_topic_config_loader(loader):
    """Set the global topic config loader reference."""
    global _topic_config_loader
    _topic_config_loader = loader


def set_jms_registry(registry):
    """Set the global JMS registry reference."""
    global _jms_registry
    _jms_registry = registry


class TopicConfigResponse(BaseModel):
    """Topic configuration response model."""
    topic: str
    message_format: str
    schema_registry_url: Optional[str] = None
    correlation_rules: Optional[dict] = None


class TopicConfigListResponse(BaseModel):
    """List of topic configurations."""
    total: int
    topics: list


class QueueManagerInfo(BaseModel):
    """Queue manager information."""
    name: str
    provider: str
    connected: bool
    config: dict


class QueueManagerListResponse(BaseModel):
    """List of queue managers."""
    total: int
    queue_managers: list


@router.get("/config/topics", tags=["Configuration"])
async def get_all_topics():
    """
    Get all configured topics.

    Returns:
        List of all topic configurations with metadata
    """
    if not _topic_config_loader:
        raise HTTPException(status_code=503, detail="Topic config loader not initialized")

    try:
        configs = _topic_config_loader.get_all_configs()
        topics = []

        for topic_name, topic_config in configs.items():
            topics.append({
                "topic": topic_name,
                "message_format": getattr(topic_config, 'message_format', 'json'),
                "schema_registry_url": getattr(topic_config, 'schema_registry_url', None),
                "has_correlation_rules": bool(getattr(topic_config, 'correlation', None))
            })

        return {
            "total": len(topics),
            "topics": topics
        }
    except Exception as e:
        logger.error(f"Failed to get topics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/topics/{topic}", tags=["Configuration"])
async def get_topic(topic: str):
    """
    Get configuration for a specific topic.

    Args:
        topic: Topic name

    Returns:
        Topic configuration details
    """
    if not _topic_config_loader:
        raise HTTPException(status_code=503, detail="Topic config loader not initialized")

    try:
        config = _topic_config_loader.get_topic_config(topic)
        if not config:
            raise HTTPException(status_code=404, detail=f"Topic '{topic}' not found")

        return {
            "topic": topic,
            "message_format": getattr(config, 'message_format', 'json'),
            "schema_registry_url": getattr(config, 'schema_registry_url', None),
            "correlation": config.correlation if hasattr(config, 'correlation') else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get topic '{topic}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/jms-queue-managers", tags=["Configuration"])
async def get_all_queue_managers():
    """
    Get all configured JMS queue managers.

    Returns:
        List of all queue manager configurations
    """
    if not _jms_registry:
        raise HTTPException(status_code=503, detail="JMS registry not initialized")

    try:
        info = _jms_registry.get_queue_manager_info()
        qms = []

        for name, details in info.items():
            qms.append({
                "name": name,
                "provider": details.get("provider", "unknown"),
                "connected": details.get("connected", False),
                "config_fields": list(details.get("config", {}).keys())
            })

        return {
            "total": len(qms),
            "queue_managers": qms
        }
    except Exception as e:
        logger.error(f"Failed to get queue managers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/jms-queue-managers/{qm_name}", tags=["Configuration"])
async def get_queue_manager(qm_name: str):
    """
    Get configuration for a specific queue manager.

    Args:
        qm_name: Queue manager reference name

    Returns:
        Queue manager configuration details
    """
    if not _jms_registry:
        raise HTTPException(status_code=503, detail="JMS registry not initialized")

    try:
        info = _jms_registry.get_queue_manager_info(qm_name)
        if "error" in info:
            raise HTTPException(status_code=404, detail=info["error"])

        # Get pool stats if available
        pool_stats = {}
        try:
            all_stats = _jms_registry.get_pool_stats()
            pool_stats = all_stats.get(qm_name, {})
        except Exception as e:
            logger.debug(f"Could not get pool stats for {qm_name}: {e}")

        return {
            "name": qm_name,
            "provider": info.get("provider"),
            "connected": info.get("connected"),
            "config": info.get("config"),
            "pool_stats": pool_stats if pool_stats else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get queue manager '{qm_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jms/providers", tags=["Configuration"])
async def get_available_providers():
    """
    Get information about available JMS providers.

    Returns:
        Dictionary with provider information (available, install command, etc.)
    """
    if not _jms_registry:
        raise HTTPException(status_code=503, detail="JMS registry not initialized")

    try:
        providers = _jms_registry.get_available_providers()

        # Format response
        result = {
            "available_providers": [],
            "unavailable_providers": []
        }

        for name, info in providers.items():
            provider_info = {
                "name": name,
                "library": info.get("library"),
                "description": info.get("description"),
                "config_fields": info.get("config_fields", [])
            }

            if info.get("available"):
                result["available_providers"].append(provider_info)
            else:
                provider_info["install_command"] = info.get("install_command")
                result["unavailable_providers"].append(provider_info)

        return result
    except Exception as e:
        logger.error(f"Failed to get available providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

