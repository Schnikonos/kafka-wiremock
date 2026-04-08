"""
Template rendering engine for message templates.
"""
import re
import logging
import uuid
import random
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Global custom placeholder registry (set by main.py)
_custom_placeholder_registry = None


def set_custom_placeholder_registry(registry):
    """Set the custom placeholder registry (called by main.py at startup)."""
    global _custom_placeholder_registry
    _custom_placeholder_registry = registry


class TemplateRenderer:
    """Renders message templates with context substitution."""

    # ...existing code...
    PLACEHOLDER_PATTERN = re.compile(r'\{\{[\s]*([a-zA-Z0-9_.$\[\](),\-+]+)[\s]*\}\}')

    @staticmethod
    def render(template: Any, context: Dict[str, Any]) -> str:
        """
        Render a template with context substitution.

        Args:
            template: The template string (or object to convert to string)
            context: Dictionary of values to substitute in placeholders

        Returns:
            Rendered template string
        """
        if template is None:
            return ""

        template_str = str(template)

        def replace_placeholder(match):
            key = match.group(1).strip()
            value = TemplateRenderer._resolve_placeholder(context, key)

            # Check if key actually exists in context (even if value is None)
            key_exists = (key in context or
                         key.startswith('header.') or
                         key == 'uuid' or key == 'now' or
                         key.startswith('now') or
                         key.startswith('randomInt(') or
                         (hasattr(context, 'get') and context.get(key) is not None))

            if value is None and not key_exists:
                logger.warning(f"Template placeholder '{{{{ {key} }}}}' not found in context. Available keys: {list(context.keys())}")
                # Return the original placeholder if not found
                return match.group(0)

            # Convert to string for substitution
            if isinstance(value, (dict, list)):
                import json
                return json.dumps(value)

            return str(value) if value is not None else ""

        return TemplateRenderer.PLACEHOLDER_PATTERN.sub(replace_placeholder, template_str)

    @staticmethod
    def _resolve_placeholder(context: Dict[str, Any], key: str) -> Optional[Any]:
        """
        Resolve a placeholder, handling built-in functions, custom placeholders, and context variables.

        Args:
            context: The context dictionary
            key: The key to retrieve or function to execute

        Returns:
            The resolved value or None if not found
        """
        # Handle built-in functions
        if key == 'uuid':
            return str(uuid.uuid4())

        if key == 'now':
            return datetime.now(timezone.utc).isoformat() + 'Z'

        # Handle now with offset like 'now+5m' or 'now-1h'
        if key.startswith('now'):
            return TemplateRenderer._resolve_now_offset(key)

        # Handle randomInt function like 'randomInt(1,100)'
        if key.startswith('randomInt(') and key.endswith(')'):
            return TemplateRenderer._resolve_random_int(key)

        # Check custom placeholder registry
        global _custom_placeholder_registry
        if _custom_placeholder_registry and _custom_placeholder_registry.get_placeholder(key):
            # Custom placeholder exists, execute it
            result = _custom_placeholder_registry.get_placeholder(key)(context)
            return result

        # Otherwise treat as context value
        return TemplateRenderer._get_context_value(context, key)

    @staticmethod
    def _resolve_now_offset(key: str) -> str:
        """
        Resolve now with optional offset like 'now+5m' or 'now-1h'.

        Args:
            key: String like 'now', 'now+5m', 'now-2h', 'now+1d'

        Returns:
            ISO-8601 timestamp string
        """
        try:
            if key == 'now':
                return datetime.now(timezone.utc).isoformat() + 'Z'

            # Parse offset like +5m, -1h, +1d, +24h (supports multi-digit numbers)
            match = re.match(r'now([+-])(\d+)([mhd])', key)
            if not match:
                logger.debug(f"Could not parse now offset: {key}")
                return datetime.now(timezone.utc).isoformat() + 'Z'

            sign, amount, unit = match.groups()
            amount = int(amount)
            if sign == '-':
                amount = -amount

            # Convert to timedelta
            if unit == 'm':
                delta = timedelta(minutes=amount)
            elif unit == 'h':
                delta = timedelta(hours=amount)
            elif unit == 'd':
                delta = timedelta(days=amount)
            else:
                return datetime.now(timezone.utc).isoformat() + 'Z'

            result_time = datetime.now(timezone.utc) + delta
            return result_time.isoformat() + 'Z'
        except Exception as e:
            logger.warning(f"Error resolving now offset '{key}': {e}")
            return datetime.now(timezone.utc).isoformat() + 'Z'

    @staticmethod
    def _resolve_random_int(key: str) -> int:
        """
        Resolve randomInt function like 'randomInt(1,100)'.

        Args:
            key: String like 'randomInt(1,100)'

        Returns:
            Random integer between min and max inclusive
        """
        try:
            # Extract numbers from 'randomInt(1,100)'
            match = re.match(r'randomInt\((\d+),(\d+)\)', key)
            if not match:
                return random.randint(0, 100)

            min_val = int(match.group(1))
            max_val = int(match.group(2))
            return random.randint(min_val, max_val)
        except Exception as e:
            logger.warning(f"Error resolving randomInt '{key}': {e}")
            return 0

    @staticmethod
    @staticmethod
    def _get_context_value(context: Dict[str, Any], key: str) -> Optional[Any]:
        """
        Get a value from context using dot notation (e.g., '$.user.name' or 'items[0]').
        Supports JSONPath-like syntax with $ prefix.

        Args:
            context: The context dictionary
            key: The key to retrieve (supports dot notation and $ prefix)

        Returns:
            The value or None if not found. Note: Returns None for both "not found" and "value is None"
        """
        # Strip leading $ if present (for JSONPath style access like $.orderId)
        if key.startswith('$.'):
            key = key[2:]
        elif key.startswith('$'):
            key = key[1:]

        # Handle simple keys - return whatever value is stored (including None)
        if key in context:
            return context[key]

        # Handle dot notation (e.g., 'user.name')
        if '.' in key or '[' in key:
            return TemplateRenderer._traverse_path(context, key)

        return None

    @staticmethod
    def _traverse_path(context: Dict[str, Any], path: str) -> Optional[Any]:
        """
        Traverse a dot-notation path in nested objects.

        Args:
            context: The root context
            path: Path like 'user.name' or 'items[0].id'

        Returns:
            The value at the path or None
        """
        try:
            # Split path handling both dots and brackets
            # e.g., "user.address[0].street" -> ["user", "address[0]", "street"]
            parts = re.split(r'\.', path)
            current = context

            for part in parts:
                # Handle array indices like "items[0]"
                if '[' in part and ']' in part:
                    key, rest = part.split('[', 1)
                    # Get the object first
                    if key and current.get(key) is not None:
                        current = current[key]

                    # Then apply all array indices
                    while '[' in rest:
                        index_str, rest = rest.split(']', 1)
                        try:
                            index = int(index_str)
                            current = current[index]
                        except (ValueError, IndexError, TypeError):
                            return None
                        if rest.startswith('.'):
                            rest = rest[1:]
                else:
                    # Simple key access
                    if isinstance(current, dict):
                        current = current.get(part)
                        if current is None:
                            return None
                    else:
                        return None

            return current
        except (KeyError, IndexError, TypeError, AttributeError):
            return None

