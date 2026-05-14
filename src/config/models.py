"""Configuration models."""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union


@dataclass
class Condition:
    """A matching condition."""
    type: str  # jsonpath, exact, partial, regex, header, key, status_code, response_header
    expression: Optional[str] = None  # for jsonpath / header / response_header
    value: Optional[Any] = None  # expected value
    regex: Optional[str] = None  # regex pattern


@dataclass
class CorrelationOutput:
    """Correlation rules for output message (may override topic-config)."""
    to_headers: Optional[Dict[str, str]] = None  # {header_name: template}


@dataclass
class Fault:
    """Fault injection configuration for output messages."""
    drop: float = 0.0
    duplicate: float = 0.0
    random_latency: Optional[str] = None  # "min-max" ms
    poison_pill: float = 0.0
    poison_pill_type: List[str] = field(default_factory=lambda: ["truncate"])
    check_result: bool = False


@dataclass
class Output:
    """Output message to a destination (Kafka topic, JMS queue, HTTP endpoint, or HTTP response)."""
    destination: str  # Kafka topic name, JMS queue name, HTTP URL, or empty string for http_response
    msg_type: str = "kafka"  # YAML key: 'type'. Values: kafka | jms | http | http_response
    payload: Optional[str] = None  # Inline payload / HTTP request body / HTTP response body
    payload_file: Optional[str] = None  # External payload file path
    delay_ms: int = 0
    headers: Optional[Dict[str, str]] = None  # Kafka/JMS headers or HTTP request/response headers
    key: Optional[str] = None  # Kafka message key template
    schema_id: Optional[int] = None  # AVRO schema ID (Kafka only)
    correlation: Optional[CorrelationOutput] = None
    fault: Optional[Fault] = None
    connection_ref: Optional[str] = None  # JMS queue manager ref (formerly queue_manager_ref)
    # HTTP-specific fields (type=http outbound call)
    method: str = "POST"  # HTTP method (type=http only)
    query_params: Optional[Dict[str, str]] = None  # HTTP query parameters
    auth_ref: Optional[str] = None  # Auth profile name (overrides host-match)
    tls_ref: Optional[str] = None  # TLS profile name (overrides host-match)
    http_timeout_ms: int = 10000  # HTTP request timeout (ms)
    # HTTP response fields (type=http_response — used in HTTP listener rules)
    status_code: int = 200           # HTTP response status code
    response_content_type: Optional[str] = None  # Response Content-Type (default: application/json)

    @property
    def message_template(self):
        """Backward compatibility property"""
        return self.payload




@dataclass
class CorrelationInput:
    """Correlation rules for input message matching (may override topic-config)."""
    extract: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Rule:
    """A matching rule with when/then structure."""
    priority: int
    input_destination: str  # Kafka topic, JMS queue name, or URL path pattern (formerly input_topic)
    conditions: List[Condition]  # All must match (AND logic)
    outputs: List[Output]
    rule_name: str = ""
    correlation: Optional[CorrelationInput] = None
    skip: bool = False
    input_type: str = "kafka"  # YAML key: 'type'. Values: kafka | jms | http (formerly input_msg_type)
    input_method: str = "*"   # HTTP method filter (type=http only). "*" matches any method.
    connection_ref: Optional[str] = None  # Server/QM ref: JMS queue manager or HTTP mock server name


    @property
    def input_msg_type(self) -> str:
        return self.input_type
