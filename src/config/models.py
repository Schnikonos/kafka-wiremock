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
class Fault:
    """Fault injection configuration for output messages."""
    drop: float = 0.0  # Probability (0.0-1.0) to drop the message entirely
    duplicate: float = 0.0  # Probability (0.0-1.0) to duplicate the message
    random_latency: Optional[str] = None  # Range as "min-max" (e.g., "0-100" ms)
    poison_pill: float = 0.0  # Probability (0.0-1.0) to corrupt the message
    poison_pill_type: List[str] = field(default_factory=lambda: ["truncate"])  # Implementation strategies: truncate, invalid-json, corrupt-headers, messageKey
    check_result: bool = False  # If True, test expectations will validate faulted messages; if False, expectations are skipped


@dataclass
class Output:
    """Output message to a topic."""
    topic: str
    payload: Optional[str] = None  # Inline payload
    payload_file: Optional[str] = None  # External payload file path (relative to rule file)
    delay_ms: int = 0
    headers: Optional[Dict[str, str]] = None
    key: Optional[str] = None  # Message key template (supports placeholders like payload/headers)
    schema_id: Optional[int] = None  # AVRO schema ID
    correlation: Optional[CorrelationOutput] = None  # Override topic-config correlation
    fault: Optional[Fault] = None  # Optional fault injection configuration

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
    skip: bool = False  # Optional; set to true to disable this rule
