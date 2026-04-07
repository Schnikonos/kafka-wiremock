"""
Test logging module - writes per-test log files with execution details.
Includes closest-match reporting when tests fail.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class LogMessage:
    """A logged message (sent or received)."""
    timestamp: str
    direction: str  # "SENT" or "RECEIVED"
    topic: str
    payload: Any
    headers: Optional[Dict[str, str]] = None
    message_id: Optional[str] = None
    source_id: Optional[str] = None
    target_id: Optional[str] = None
    correlation_matched: bool = False
    conditions_matched: int = 0
    total_conditions: int = 0


class TestLogger:
    """Logs test execution details to per-test YAML log files."""

    def __init__(self, test_file_path: Path, verbose: bool = False):
        """
        Initialize test logger.

        Args:
            test_file_path: Path to the test YAML file
            verbose: If True, log skipped messages and details
        """
        self.test_file_path = Path(test_file_path).resolve()  # Convert to absolute path
        # Replace .test.yaml or .test.yml with .test.log
        if str(self.test_file_path).endswith('.test.yaml'):
            self.log_file_path = Path(str(self.test_file_path).replace('.test.yaml', '.test.log'))
        elif str(self.test_file_path).endswith('.test.yml'):
            self.log_file_path = Path(str(self.test_file_path).replace('.test.yml', '.test.log'))
        else:
            # Fallback: just append .log
            self.log_file_path = self.test_file_path.with_suffix('.log')

        logger.info(f"TestLogger initialized for {self.test_file_path}")
        logger.info(f"  Log file will be written to: {self.log_file_path}")
        logger.info(f"  Log file absolute path: {self.log_file_path.absolute()}")
        self.verbose = verbose
        self.sent_messages: List[LogMessage] = []
        self.received_messages: List[LogMessage] = []
        self.skipped_messages: List[LogMessage] = []
        self.expectations_results: List[Dict[str, Any]] = []

    def log_sent_message(
        self,
        topic: str,
        payload: Any,
        message_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        """Log a message sent during test setup (when phase)."""
        msg = LogMessage(
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            direction="SENT",
            topic=topic,
            payload=payload,
            headers=headers,
            message_id=message_id
        )
        self.sent_messages.append(msg)

    def log_received_message(
        self,
        topic: str,
        payload: Any,
        message_id: Optional[str] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        correlation_matched: bool = False,
        conditions_matched: int = 0,
        total_conditions: int = 0,
        headers: Optional[Dict[str, str]] = None
    ):
        """Log a message received during test validation (then phase)."""
        msg = LogMessage(
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            direction="RECEIVED",
            topic=topic,
            payload=payload,
            headers=headers,
            message_id=message_id,
            source_id=source_id,
            target_id=target_id,
            correlation_matched=correlation_matched,
            conditions_matched=conditions_matched,
            total_conditions=total_conditions
        )
        self.received_messages.append(msg)

    def log_skipped_message(
        self,
        topic: str,
        payload: Any,
        reason: str,
        headers: Optional[Dict[str, str]] = None
    ):
        """Log a message that was skipped (verbose mode only)."""
        if not self.verbose:
            return
        msg = LogMessage(
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            direction="SKIPPED",
            topic=topic,
            payload=payload,
            headers=headers
        )
        self.skipped_messages.append(msg)

    def log_expectation_result(self, result: Dict[str, Any]):
        """Log expectation result."""
        self.expectations_results.append(result)

    def find_closest_match(self) -> Optional[Dict[str, Any]]:
        """
        Find the closest non-matching message when test fails.

        Returns closest by priority:
        1. Messages with correct correlation (message_id + source_id match)
        2. Messages matching most conditions
        3. First message received on correct topic

        Returns:
            Dict with message and match score, or None
        """
        if not self.received_messages:
            return None

        candidates = []

        for msg in self.received_messages:
            # Tier 1: Correlation matched
            if msg.correlation_matched:
                candidates.append((1, msg.conditions_matched, msg))
            # Tier 2: Conditions matched (but not correlation)
            elif msg.conditions_matched > 0:
                candidates.append((2, msg.conditions_matched, msg))
            # Tier 3: Any message on topic
            else:
                candidates.append((3, 0, msg))

        if not candidates:
            return None

        # Sort by tier (lower = better), then by conditions matched (higher = better)
        candidates.sort(key=lambda x: (x[0], -x[1]))
        tier, conditions_matched, best_msg = candidates[0]

        return {
            "message": asdict(best_msg),
            "tier": tier,
            "tier_name": {1: "correlation_matched", 2: "partial_match", 3: "topic_only"}.get(tier),
            "conditions_matched": conditions_matched,
            "total_conditions": best_msg.total_conditions
        }

    def find_perfect_match(self) -> Optional[Dict[str, Any]]:
        """
        Find a perfectly matching message (all conditions + correlation matched).

        Returns:
            Dict with the perfect matching message, or None
        """
        if not self.received_messages:
            return None

        # Find messages that matched all conditions and correlation
        for msg in self.received_messages:
            # Perfect match: correlation matched and all conditions matched
            if msg.correlation_matched and msg.conditions_matched == msg.total_conditions:
                return {
                    "message": asdict(msg),
                    "tier": "perfect_match",
                    "conditions_matched": msg.conditions_matched,
                    "total_conditions": msg.total_conditions
                }
            # Alternative: all conditions matched even without explicit correlation check
            elif msg.conditions_matched == msg.total_conditions and msg.total_conditions > 0:
                return {
                    "message": asdict(msg),
                    "tier": "perfect_match",
                    "conditions_matched": msg.conditions_matched,
                    "total_conditions": msg.total_conditions
                }

        return None

    def write_log_file(self, test_name: str, status: str, elapsed_ms: int, errors: List[str]):
        """
        Write test execution log to file.

        Args:
            test_name: Name of the test
            status: Test status (PASSED, FAILED, SKIPPED, TIMEOUT)
            elapsed_ms: Execution time in milliseconds
            errors: List of error messages
        """
        try:
            logger.info(f"Writing test log to: {self.log_file_path}")

            # Ensure parent directory exists
            self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Build log content
            log_content = {
                "test_name": test_name,
                "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "elapsed_ms": elapsed_ms,
                "errors": errors,
                "sent_messages": [self._msg_to_dict(m) for m in self.sent_messages],
            }

            # Add received_messages only in verbose mode
            if self.verbose:
                log_content["received_messages"] = [self._msg_to_dict(m) for m in self.received_messages]

            # Add verbose info if enabled
            if self.verbose and self.skipped_messages:
                log_content["skipped_messages"] = [self._msg_to_dict(m) for m in self.skipped_messages]

            # Add match summary based on test status (always, regardless of verbose mode)
            if status == "PASSED":
                perfect = self.find_perfect_match()
                if perfect:
                    log_content["perfect_match"] = perfect
            elif status == "FAILED":
                closest = self.find_closest_match()
                if closest:
                    log_content["closest_match"] = closest

            # Add expectations results
            if self.expectations_results:
                log_content["expectations"] = self.expectations_results

            # Write as YAML-like format (for readability)
            with open(self.log_file_path, "w") as f:
                f.write(self._to_yaml_string(log_content))

            logger.info(f"Test log successfully written to {self.log_file_path}")

        except Exception as e:
            logger.error(f"Failed to write test log file to {self.log_file_path}: {e}", exc_info=True)

    @staticmethod
    def _msg_to_dict(msg: LogMessage) -> Dict[str, Any]:
        """Convert LogMessage to dict, excluding None values."""
        d = asdict(msg)
        return {k: v for k, v in d.items() if v is not None}

    @staticmethod
    def _to_yaml_string(data: Dict[str, Any], indent: int = 0) -> str:
        """Convert dict to YAML-like string format."""
        result = []
        for key, value in data.items():
            prefix = "  " * indent
            if isinstance(value, dict):
                result.append(f"{prefix}{key}:")
                result.append(TestLogger._to_yaml_string(value, indent + 1))
            elif isinstance(value, list):
                if not value:
                    result.append(f"{prefix}{key}: []")
                elif isinstance(value[0], dict):
                    result.append(f"{prefix}{key}:")
                    for item in value:
                        result.append(f"{prefix}  - {TestLogger._to_yaml_string(item, indent + 2).strip()}")
                else:
                    result.append(f"{prefix}{key}:")
                    for item in value:
                        result.append(f"{prefix}  - {json.dumps(item) if isinstance(item, (dict, list)) else item}")
            else:
                # Format value
                if isinstance(value, bool):
                    val_str = "true" if value else "false"
                elif isinstance(value, str):
                    val_str = f'"{value}"'
                elif isinstance(value, (dict, list)):
                    val_str = json.dumps(value)
                else:
                    val_str = str(value)
                result.append(f"{prefix}{key}: {val_str}")

        return "\n".join(result)

