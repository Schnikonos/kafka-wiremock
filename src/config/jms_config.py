"""JMS configuration models."""
from dataclasses import dataclass, field
from typing import Dict, Optional, Any


@dataclass
class JMSConfig:
    """Configuration for a JMS destination (queue/topic)."""

    destination: str  # Queue or topic name
    queue_manager_ref: str = "default"  # Reference to queue manager config (NEW)
    provider: str = "ibm_mq"  # JMS provider type (NEW)
    destination_type: str = "queue"  # "queue" or "topic"
    message_format: str = "json"  # json, avro, text, bytes
    jms_properties: Optional[Dict[str, Any]] = None  # Custom JMS properties
    correlation: Optional[Dict[str, Any]] = None  # Correlation extraction/propagation rules

    @property
    def name(self) -> str:
        """Alias for destination for compatibility."""
        return self.destination

