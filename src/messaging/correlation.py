"""
Shared correlation helpers used by Kafka listener, JMS listener, and test suite.

Two public functions:
  extract_correlation_id(message_data, headers, config) -> Optional[str]
  apply_propagation(existing_headers, correlation_id, config) -> dict

Both accept either a CorrelationConfig object (Kafka/topic-config path)
or a raw dict (JMS-config path) via _normalise_corr_config().
"""
import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: normalise CorrelationConfig or raw dict → CorrelationConfig
# ---------------------------------------------------------------------------

def _normalise_corr_config(config):
    """
    Accept either a CorrelationConfig dataclass or a raw dict (JMS style)
    and return a CorrelationConfig (or None if config is None / empty).
    """
    if config is None:
        return None

    # Already a CorrelationConfig — return as-is
    try:
        from ..config.topic_config import CorrelationConfig
        if isinstance(config, CorrelationConfig):
            return config
    except ImportError:
        pass

    # Raw dict (JMS-config) — parse into a CorrelationConfig
    if isinstance(config, dict):
        try:
            from ..config.topic_config import (
                CorrelationConfig,
                CorrelationExtractRule,
                CorrelationPropagateRule,
            )
            extract_rules: List[CorrelationExtractRule] = []
            for idx, rule_data in enumerate(config.get("extract") or []):
                try:
                    rule = CorrelationExtractRule(
                        from_type=rule_data.get("from", "header"),
                        name=rule_data.get("name"),
                        expression=rule_data.get("expression"),
                        priority=rule_data.get("priority", idx),
                    )
                    extract_rules.append(rule)
                except Exception as e:
                    logger.debug(f"Skipping invalid extract rule: {e}")

            extract_rules.sort(key=lambda r: r.priority)

            propagate = None
            prop_data = config.get("propagate")
            if prop_data:
                propagate = CorrelationPropagateRule(
                    to_headers=prop_data.get("to_headers") or {}
                )

            return CorrelationConfig(extract=extract_rules, propagate=propagate)
        except Exception as e:
            logger.debug(f"Failed to normalise correlation config dict: {e}")
            return None

    logger.debug(f"Unknown correlation config type: {type(config)}")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_correlation_id(
    message_data: Any,
    headers: Optional[Dict[str, str]],
    config,
) -> Optional[str]:
    """
    Try each extract rule (priority order) and return the first match.

    Args:
        message_data: Parsed message payload (dict or string).
        headers: Message headers dict (may be None).
        config: CorrelationConfig dataclass or raw dict, or None.

    Returns:
        The extracted correlation ID string, or None if no rule matches.
    """
    corr_cfg = _normalise_corr_config(config)
    if corr_cfg is None:
        return None

    for rule in corr_cfg.extract:
        try:
            if rule.from_type == "header":
                if headers and rule.name and rule.name in headers:
                    value = headers[rule.name]
                    if value:
                        logger.debug(f"Extracted correlationId from header '{rule.name}': {value!r}")
                        return str(value)

            elif rule.from_type == "jsonpath":
                if message_data and rule.expression:
                    try:
                        from jsonpath_ng import parse as jp_parse
                        matches = jp_parse(rule.expression).find(message_data)
                        if matches:
                            value = matches[0].value
                            if value is not None:
                                logger.debug(
                                    f"Extracted correlationId from jsonpath '{rule.expression}': {value!r}"
                                )
                                return str(value)
                    except Exception as e:
                        logger.debug(f"JSONPath extraction failed for '{rule.expression}': {e}")

        except Exception as e:
            logger.debug(f"Error applying extract rule {rule}: {e}")

    return None


def apply_propagation(
    existing_headers: Optional[Dict[str, str]],
    correlation_id: str,
    config,
) -> dict:
    """
    Return a copy of existing_headers with correlation_id stamped in according to rules.

    Strategy:
      1. If config.propagate.to_headers exists → use those mappings (supports {{correlationId}} template).
      2. Else fall back to writing correlation_id into the same location as config.extract rules:
         - header-type extract → set that header
         - jsonpath-type extract → left to caller (not modified here; only headers are managed)
      3. If config is None or correlation_id is empty → return copy of existing_headers unchanged.

    Args:
        existing_headers: Current headers dict (may be None).
        correlation_id: The correlation ID value to stamp.
        config: CorrelationConfig dataclass or raw dict, or None.

    Returns:
        New headers dict (never mutates existing_headers).
    """
    headers = dict(existing_headers or {})
    if not correlation_id:
        return headers

    corr_cfg = _normalise_corr_config(config)
    if corr_cfg is None:
        return headers

    # Strategy 1: explicit propagate.to_headers mapping
    if corr_cfg.propagate and corr_cfg.propagate.to_headers:
        for header_name, template in corr_cfg.propagate.to_headers.items():
            try:
                value = template.replace("{{correlationId}}", correlation_id)
                headers[header_name] = value
                logger.debug(f"Propagated correlationId to header '{header_name}'")
            except Exception as e:
                logger.debug(f"Error propagating to header '{header_name}': {e}")
        return headers

    # Strategy 2: fall back to extract rules (header-type only)
    for rule in corr_cfg.extract:
        try:
            if rule.from_type == "header" and rule.name:
                headers[rule.name] = correlation_id
                logger.debug(f"Propagated correlationId (fallback) to header '{rule.name}'")
        except Exception as e:
            logger.debug(f"Error in fallback propagation for rule {rule}: {e}")

    return headers

