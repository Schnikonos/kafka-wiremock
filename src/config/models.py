"""Configuration models."""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class Condition:
    """A matching condition."""
    type: str  # jsonpath, exact, partial, regex
    expression: Optional[str] = None  # for jsonpath
    value: Optional[Any] = None  # expected value
    regex: Optional[str] = None  # regex pattern


@dataclass
class CorrelationOutput:
    """Correlation rules for output message (may override topic-config)."""
    to_headers: Optional[Dict[str, str]] = None  # {header_name: template}


@dataclass
class Output:
    """Output message to a topic."""
    topic: str
    payload: Optional[str] = None  # Inline payload
    payload_file: Optional[str] = None  # External payload file path (relative to rule file)
    delay_ms: int = 0
    headers: Optional[Dict[str, str]] = None
    schema_id: Optional[int] = None  # AVRO schema ID
    correlation: Optional[CorrelationOutput] = None  # Override topic-config correlation

    @property
    def message_template(self):
        """Backward compatibility property"""
        return self.payload


@dataclass
class CorrelationInput:
    """Correlation rules for input message matching (may override topic-config)."""
    extract: List[Dict[str, Any]] = field(default_factory=list)  # [{"from": "header", "name": "..."}, ...]


@dataclass
class Rule:
    """A matching rule with when/then structure."""
    priority: int
    input_topic: str
    conditions: List[Condition]  # All must match (AND logic)
    outputs: List[Output]
    rule_name: str = ""
    correlation: Optional[CorrelationInput] = None  # Override topic-config correlation
