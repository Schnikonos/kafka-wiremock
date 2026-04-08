"""
Message matching engine supporting multiple strategies.
"""
import re
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JSONPathError

logger = logging.getLogger(__name__)


class MatchResult:
    """Result of a message matching attempt."""

    def __init__(self, matched: bool, context: Dict[str, Any] = None):
        self.matched = matched
        self.context = context or {}


class Matcher(ABC):
    """Abstract base class for message matching strategies."""

    @abstractmethod
    def match(self, message: Any, condition: Any) -> MatchResult:
        """
        Match a message against a condition.

        Args:
            message: The message to match (str, dict, or bytes)
            condition: The condition to match against

        Returns:
            MatchResult with matched flag and context dict
        """
        pass


class ExactMatcher(Matcher):
    """Exact string matching strategy."""

    def match(self, message: Any, condition: Any) -> MatchResult:
        """Match if message exactly equals condition."""
        try:
            if isinstance(message, bytes):
                message = message.decode('utf-8')

            condition_str = str(condition)
            message_str = str(message)

            matched = message_str == condition_str
            return MatchResult(matched, {"full_message": message_str})
        except Exception as e:
            logger.warning(f"ExactMatcher error: {e}")
            return MatchResult(False)


class PartialMatcher(Matcher):
    """Partial string matching (substring) strategy."""

    def match(self, message: Any, condition: Any) -> MatchResult:
        """Match if condition is a substring of message."""
        try:
            if isinstance(message, bytes):
                message = message.decode('utf-8')

            condition_str = str(condition)
            message_str = str(message)

            matched = condition_str in message_str
            return MatchResult(matched, {"full_message": message_str})
        except Exception as e:
            logger.warning(f"PartialMatcher error: {e}")
            return MatchResult(False)


class RegexMatcher(Matcher):
    """Regular expression matching strategy."""

    def match(self, message: Any, condition: Any) -> MatchResult:
        """Match if message matches the regex pattern in condition."""
        try:
            if isinstance(message, bytes):
                message = message.decode('utf-8')

            pattern = str(condition)
            message_str = str(message)

            compiled_pattern = re.compile(pattern)
            match_obj = compiled_pattern.search(message_str)

            if match_obj:
                # Include named groups and full match in context
                context = {"full_message": message_str}
                context.update(match_obj.groupdict())
                if match_obj.groups():
                    # Add numbered groups
                    for i, group in enumerate(match_obj.groups(), 1):
                        if f"group_{i}" not in context:
                            context[f"group_{i}"] = group
                return MatchResult(True, context)
            else:
                return MatchResult(False, {"full_message": message_str})
        except re.error as e:
            logger.warning(f"RegexMatcher: Invalid pattern '{condition}': {e}")
            return MatchResult(False)
        except Exception as e:
            logger.warning(f"RegexMatcher error: {e}")
            return MatchResult(False)


class JSONPathMatcher(Matcher):
    """JSONPath matching strategy for JSON messages."""

    def match(self, message: Any, condition: Any) -> MatchResult:
        """Match using JSONPath query on JSON message."""
        try:
            # Try to parse as JSON if it's a string
            if isinstance(message, (str, bytes)):
                if isinstance(message, bytes):
                    message = message.decode('utf-8')
                try:
                    message_obj = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning("JSONPathMatcher: Message is not valid JSON")
                    return MatchResult(False)
            else:
                message_obj = message

            # condition can be a dict with 'path' and either 'value' or 'regex'
            if isinstance(condition, dict):
                path = condition.get('path')
                expected_value = condition.get('value')
                regex_pattern = condition.get('regex')
            else:
                logger.warning("JSONPathMatcher: Condition must be a dict with 'path' and 'value' or 'regex'")
                return MatchResult(False)

            if not path:
                logger.warning("JSONPathMatcher: No 'path' in condition")
                return MatchResult(False)

            # Parse and execute JSONPath
            jsonpath_expr = jsonpath_parse(path)
            matches = jsonpath_expr.find(message_obj)

            if not matches:
                return MatchResult(False, {"message": message_obj})

            # Check if any match satisfies the condition
            for match in matches:
                # If regex pattern is provided, use regex matching
                if regex_pattern:
                    try:
                        if re.search(regex_pattern, str(match.value)):
                            # Return context with the matched value
                            context = {"message": message_obj, "matched_value": match.value}
                            context.update(flatten_dict(message_obj))
                            return MatchResult(True, context)
                    except re.error as e:
                        logger.warning(f"JSONPathMatcher: Invalid regex pattern '{regex_pattern}': {e}")
                        continue
                # Otherwise use exact value matching
                elif expected_value is not None and match.value == expected_value:
                    # Return context with the matched value
                    context = {"message": message_obj, "matched_value": match.value}
                    context.update(flatten_dict(message_obj))
                    return MatchResult(True, context)

            return MatchResult(False, {"message": message_obj})

        except JSONPathError as e:
            logger.warning(f"JSONPathMatcher: Invalid JSONPath '{condition}': {e}")
            return MatchResult(False)
        except Exception as e:
            logger.warning(f"JSONPathMatcher error: {e}")
            return MatchResult(False)


class HeaderMatcher(Matcher):
    """Header value matching strategy."""

    def match(self, headers: Any, condition: Any) -> MatchResult:
        """
        Match against message headers.

        Args:
            headers: Dictionary of headers from the message
            condition: Condition object with 'expression' (header name), 'value' or 'regex'

        Returns:
            MatchResult with match status
        """
        try:
            if not isinstance(headers, dict):
                logger.debug(f"HeaderMatcher: headers is not a dict, got {type(headers)}")
                return MatchResult(False)

            # Get header name from condition.expression
            header_name = condition.expression if hasattr(condition, 'expression') else None
            if not header_name:
                logger.warning("HeaderMatcher requires condition.expression (header name)")
                return MatchResult(False)

            # Get the header value
            header_value = headers.get(header_name)
            if header_value is None:
                logger.debug(f"Header '{header_name}' not found in message headers. Available: {list(headers.keys())}")
                return MatchResult(False)

            # Check value match if specified
            if hasattr(condition, 'value') and condition.value:
                matched = str(header_value) == str(condition.value)
                logger.debug(f"HeaderMatcher: Comparing '{header_name}': '{header_value}' == '{condition.value}' -> {matched}")
                return MatchResult(matched, {f"header.{header_name}": header_value})

            # Check regex match if specified
            if hasattr(condition, 'regex') and condition.regex:
                try:
                    pattern = re.compile(condition.regex)
                    matched = pattern.search(str(header_value)) is not None
                    logger.debug(f"HeaderMatcher: Regex '{condition.regex}' against '{header_value}' -> {matched}")
                    return MatchResult(matched, {f"header.{header_name}": header_value})
                except Exception as e:
                    logger.warning(f"HeaderMatcher regex error: {e}")
                    return MatchResult(False)

            # No value or regex specified, just check header exists
            logger.debug(f"HeaderMatcher: Header '{header_name}' exists with value '{header_value}'")
            return MatchResult(True, {f"header.{header_name}": header_value})

        except Exception as e:
            logger.warning(f"HeaderMatcher error: {e}")
            return MatchResult(False)


class KeyMatcher(Matcher):
    """Message key matching strategy."""

    def match(self, key: Any, condition: Any) -> MatchResult:
        """
        Match against message key.

        Args:
            key: Message key from the Kafka message
            condition: Condition object with 'value' or 'regex'

        Returns:
            MatchResult with match status
        """
        try:
            if key is None:
                logger.debug("KeyMatcher: Message key is None")
                return MatchResult(False)

            key_str = str(key)

            # Check value match if specified
            if hasattr(condition, 'value') and condition.value:
                matched = key_str == str(condition.value)
                logger.debug(f"KeyMatcher: Comparing key '{key_str}' == '{condition.value}' -> {matched}")
                return MatchResult(matched, {"messageKey": key_str})

            # Check regex match if specified
            if hasattr(condition, 'regex') and condition.regex:
                try:
                    pattern = re.compile(condition.regex)
                    matched = pattern.search(key_str) is not None
                    logger.debug(f"KeyMatcher: Regex '{condition.regex}' against '{key_str}' -> {matched}")
                    return MatchResult(matched, {"messageKey": key_str})
                except Exception as e:
                    logger.warning(f"KeyMatcher regex error: {e}")
                    return MatchResult(False)

            # No value or regex specified, just check key exists
            logger.debug(f"KeyMatcher: Message key exists with value '{key_str}'")
            return MatchResult(True, {"messageKey": key_str})

        except Exception as e:
            logger.warning(f"KeyMatcher error: {e}")
            return MatchResult(False)


def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
    """Flatten a nested dictionary for template context."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            items.append((new_key, v))
            # Also add individual items
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    items.extend(flatten_dict(item, f"{new_key}[{i}]", sep=sep).items())
                else:
                    items.append((f"{new_key}[{i}]", item))
        else:
            items.append((new_key, v))
    return dict(items)


class MatcherFactory:
    """Factory for creating matcher instances."""

    STRATEGIES = {
        'exact': ExactMatcher,
        'partial': PartialMatcher,
        'regex': RegexMatcher,
        'jsonpath': JSONPathMatcher,
        'header': HeaderMatcher,
        'key': KeyMatcher,
    }

    @staticmethod
    def create(strategy: str) -> Matcher:
        """Create a matcher for the given strategy."""
        matcher_class = MatcherFactory.STRATEGIES.get(strategy.lower())
        if not matcher_class:
            raise ValueError(f"Unknown matching strategy: {strategy}. Available: {list(MatcherFactory.STRATEGIES.keys())}")
        return matcher_class()

