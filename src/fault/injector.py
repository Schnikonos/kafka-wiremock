"""
Fault injection engine for simulating message failures.
"""
import json
import random
import logging
from typing import Any, List, Optional, Tuple
from src.config.models import Fault

logger = logging.getLogger(__name__)


class FaultInjector:
    """Executes fault injection on messages."""

    @staticmethod
    def apply_fault(message: Any, fault: Fault, is_json: bool = True) -> Tuple[bool, Any]:
        """
        Apply fault injection to a message.

        Args:
            message: The message to potentially fault (dict or string)
            fault: Fault configuration
            is_json: Whether message is JSON (for poison-pill)

        Returns:
            Tuple of (should_produce, modified_message)
            - should_produce: False if message was dropped, True otherwise
            - modified_message: The (potentially corrupted) message
        """
        logger.debug(f"Applying fault injection: drop={fault.drop}, duplicate={fault.duplicate}, "
                     f"random_latency={fault.random_latency}, poison_pill={fault.poison_pill}")

        # Apply DROP (prevent production entirely)
        if FaultInjector._should_fault(fault.drop):
            logger.info(f"Fault: Message dropped (drop probability {fault.drop})")
            return False, None

        # Apply POISON-PILL (corrupt the message)
        if FaultInjector._should_fault(fault.poison_pill):
            logger.info(f"Fault: Message poisoned (poison_pill probability {fault.poison_pill}, "
                        f"type={fault.poison_pill_type})")
            message = FaultInjector._apply_poison_pill(message, fault.poison_pill_type, is_json)

        # Note: DUPLICATE is handled by caller (produce twice)
        # Note: RANDOM-LATENCY is handled by caller (sleep)

        return True, message

    @staticmethod
    def should_duplicate(fault: Fault) -> bool:
        """Check if message should be duplicated."""
        return FaultInjector._should_fault(fault.duplicate)

    @staticmethod
    def get_random_latency_ms(fault: Fault) -> Optional[int]:
        """
        Extract random latency from range string (e.g., "0-100" -> random int 0-100).

        Args:
            fault: Fault configuration

        Returns:
            Random milliseconds, or None if no random_latency configured
        """
        if not fault.random_latency:
            return None

        try:
            parts = fault.random_latency.split('-')
            if len(parts) != 2:
                logger.warning(f"Invalid random_latency format: {fault.random_latency}. Expected 'min-max'")
                return None

            min_ms = int(parts[0].strip())
            max_ms = int(parts[1].strip())

            if min_ms < 0 or max_ms < 0 or min_ms > max_ms:
                logger.warning(f"Invalid random_latency range: {fault.random_latency}. min={min_ms}, max={max_ms}")
                return None

            latency = random.randint(min_ms, max_ms)
            logger.debug(f"Random latency: {latency}ms (range {min_ms}-{max_ms})")
            return latency
        except (ValueError, AttributeError) as e:
            logger.error(f"Error parsing random_latency '{fault.random_latency}': {e}")
            return None

    @staticmethod
    def _should_fault(probability: float) -> bool:
        """Check if fault should occur based on probability."""
        if probability <= 0.0:
            return False
        if probability >= 1.0:
            return True
        return random.random() < probability

    @staticmethod
    def _apply_poison_pill(message: Any, types: List[str], is_json: bool) -> Any:
        """
        Apply poison-pill corruption to message.

        Args:
            message: Message to corrupt
            types: List of corruption types: 'truncate', 'invalid-json', 'corrupt-headers', 'messageKey'
            is_json: Whether message is JSON

        Returns:
            Corrupted message
        """
        if not types:
            types = ['truncate']

        # Pick random corruption type
        chosen_type = random.choice(types)
        logger.debug(f"Applying poison-pill type: {chosen_type}")

        if chosen_type == 'truncate':
            return FaultInjector._truncate_message(message)
        elif chosen_type == 'invalid-json':
            return FaultInjector._make_invalid_json(message)
        elif chosen_type == 'corrupt-headers':
            # For this implementation, we corrupt the message itself
            # (Header corruption is typically handled at Kafka producer level)
            return FaultInjector._corrupt_message(message)
        elif chosen_type == 'messageKey':
            # messageKey poison pill is handled at producer level, not here
            # Message itself is not modified for this type
            logger.debug("messageKey poison pill will be applied by producer")
            return message
        else:
            logger.warning(f"Unknown poison-pill type: {chosen_type}")
            return message

    @staticmethod
    def _truncate_message(message: Any) -> str:
        """Truncate message to random length."""
        message_str = json.dumps(message) if isinstance(message, dict) else str(message)
        # Truncate to 50-90% of length to create invalid JSON
        truncate_point = random.randint(int(len(message_str) * 0.5), int(len(message_str) * 0.9))
        truncated = message_str[:truncate_point]
        logger.debug(f"Truncated message from {len(message_str)} to {len(truncated)} characters")
        return truncated

    @staticmethod
    def _make_invalid_json(message: Any) -> str:
        """Make message invalid JSON by removing closing braces."""
        message_str = json.dumps(message) if isinstance(message, dict) else str(message)
        # Remove random closing braces/brackets to break JSON
        if len(message_str) > 10:
            corrupt_point = random.randint(len(message_str) - 5, len(message_str) - 1)
            corrupted = message_str[:corrupt_point]
            logger.debug(f"Created invalid JSON by truncating to position {corrupt_point}")
            return corrupted
        return message_str

    @staticmethod
    def _corrupt_message(message: Any) -> Any:
        """Corrupt message by adding random garbage."""
        if isinstance(message, dict):
            # Add corrupted field
            message = dict(message)  # Copy
            message['__corrupted'] = ''.join(random.choices('abc\x00\xff', k=10))
            logger.debug("Added corrupted field to message")
            return message
        else:
            message_str = str(message)
            # Inject random bytes
            inject_pos = random.randint(0, len(message_str))
            corrupted = message_str[:inject_pos] + '\x00\xff' + message_str[inject_pos:]
            logger.debug(f"Injected garbage bytes at position {inject_pos}")
            return corrupted

    @staticmethod
    def apply_messagekey_poison_pill(key: Optional[str]) -> str:
        """
        Apply messageKey poison pill by generating a corrupted key.

        Args:
            key: Original message key (or None)

        Returns:
            Corrupted random key string
        """
        # Generate random corrupted key
        corrupted_key = ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_', k=16))
        logger.debug(f"Corrupted messageKey from '{key}' to '{corrupted_key}'")
        return corrupted_key
