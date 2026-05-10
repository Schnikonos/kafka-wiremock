"""
Rules management endpoints.
"""
import logging
import json
from typing import Dict, Any, Optional, Union, List
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["rules"])

# Global references - will be set by main.py
_config_loader = None
_listener_engine = None


class RuleMatchRequest(BaseModel):
    """Request model for rule matching test"""
    payload: Union[Dict[str, Any], str]
    key: Optional[str] = None
    headers: Optional[Dict[str, str]] = None


def set_config_loader(loader):
    """Set the global config loader reference."""
    global _config_loader
    _config_loader = loader


def set_listener_engine(engine):
    """Set the global listener engine reference."""
    global _listener_engine
    _listener_engine = engine


def _serialize_rule(rule) -> Dict[str, Any]:
    """Convert a Rule object to a dictionary for JSON serialization."""
    outputs = [
        {
            "topic": output.topic,
            "payload": output.payload,
            "delay_ms": output.delay_ms,
            "headers": output.headers,
            "schema_id": output.schema_id
        }
        for output in rule.outputs
    ]
    conditions = [
        {
            "type": cond.type,
            "expression": cond.expression,
            "value": cond.value,
            "regex": cond.regex
        }
        for cond in rule.conditions
    ]
    return {
        "name": rule.rule_name,
        "priority": rule.priority,
        "conditions": conditions,
        "input_topic": rule.input_topic,
        "outputs": outputs,
    }


@router.get("/rules")
async def get_rules(errors: bool = Query(False, description="If true, include validation errors")):
    """
    Get all configured rules.

    Args:
        errors: If true, include validation errors for all rule files

    Returns:
        List of rules with details, optionally including validation errors
    """
    if not _config_loader:
        raise HTTPException(status_code=503, detail="Config loader not initialized")
    try:
        rules = _config_loader.get_all_rules()
        result = [_serialize_rule(rule) for rule in rules]

        response = {"rules": result}

        # Add validation errors if requested
        if errors:
            response["validation_errors"] = _config_loader.validation_errors or {}
            response["has_errors"] = bool(_config_loader.validation_errors)

        return response
    except Exception as e:
        logger.error(f"Error retrieving rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rules/{input_topic}")
async def get_rules_for_topic(input_topic: str):
    """
    Get rules for a specific input topic.
    Args:
        input_topic: Input topic name
    Returns:
        Rules that apply to this topic
    """
    if not _config_loader:
        raise HTTPException(status_code=503, detail="Config loader not initialized")
    try:
        rules = _config_loader.get_rules_for_topic(input_topic)
        result = [_serialize_rule(rule) for rule in rules]
        return result
    except Exception as e:
        logger.error(f"Error retrieving rules for topic {input_topic}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rules:match")
async def explain_rule_match(
    topic: str = Query(..., description="Input topic"),
    rule_name: Optional[str] = Query(None, description="Filter to specific rule (optional)"),
    request: RuleMatchRequest = Body(..., description="Message with payload, key, and headers")
) -> Dict[str, Any]:
    """
    Dry-run endpoint: Show which rule would match a message and why.

    Args:
        topic: Input topic for the message
        rule_name: Optional specific rule to test
        request: RuleMatchRequest with payload, key, and headers

    Returns:
        Matching rule details with matcher context and extraction results
    """
    if not _config_loader or not _listener_engine:
        raise HTTPException(status_code=503, detail="Services not initialized")

    try:
        # Import MatcherFactory here
        from ..rules.matcher import MatcherFactory

        # Get rules for the topic
        rules = _config_loader.get_rules_for_topic(topic)

        # Filter by rule name if specified
        if rule_name:
            rules = [r for r in rules if r.rule_name == rule_name]

        if not rules:
            return {
                "matched": False,
                "message": "No rules configured for this topic",
                "message_preview": str(request.payload)[:200],
                "topic": topic,
                "evaluated_rules": 0
            }

        # Try to match each rule
        for rule in rules:
            matched_all_conditions = True
            context = {}
            conditions_detail = []

            # Check all conditions
            for i, condition in enumerate(rule.conditions):
                try:
                    # Create matcher based on condition type
                    matcher = MatcherFactory.create(condition.type)

                    # Prepare data to match based on condition type
                    if condition.type == 'jsonpath':
                        match_condition = {
                            'path': condition.expression,
                            'value': condition.value,
                            'regex': condition.regex
                        }
                        match_data = request.payload
                    elif condition.type == 'key':
                        match_condition = condition
                        match_data = request.key
                    elif condition.type == 'header':
                        match_condition = condition
                        match_data = request.headers or {}
                    else:
                        match_condition = condition.regex if condition.regex else condition.value
                        match_data = request.payload

                    # Match the condition
                    match_result = matcher.match(match_data, match_condition)

                    conditions_detail.append({
                        "index": i,
                        "type": condition.type,
                        "expression": condition.expression,
                        "value": condition.value,
                        "regex": condition.regex,
                        "matched": match_result.matched
                    })

                    if not match_result.matched:
                        matched_all_conditions = False

                    # Add context from this match to the overall context
                    context.update(match_result.context)

                except Exception as e:
                    logger.warning(f"Error matching condition {i}: {e}")
                    matched_all_conditions = False
                    conditions_detail.append({
                        "index": i,
                        "type": condition.type,
                        "matched": False,
                        "error": str(e)
                    })

            # If all conditions matched, return rule details
            if matched_all_conditions:
                return {
                    "matched": True,
                    "rule": {
                        "name": rule.rule_name,
                        "priority": rule.priority,
                        "input_topic": rule.input_topic
                    },
                    "conditions": conditions_detail,
                    "context": context,
                    "message_preview": str(request.payload)[:200],
                    "topic": topic,
                    "outputs_count": len(rule.outputs),
                    "outputs": [{"topic": o.topic, "delay_ms": o.delay_ms} for o in rule.outputs]
                }

        # No rule matched
        return {
            "matched": False,
            "message": "No rules matched this message",
            "message_preview": str(request.payload)[:200],
            "topic": topic,
            "evaluated_rules": len(rules),
            "available_rules": [
                {
                    "name": r.rule_name,
                    "priority": r.priority,
                    "conditions": len(r.conditions)
                }
                for r in rules
            ]
        }
    except Exception as e:
        logger.error(f"Error explaining rule match: {e}")
        raise HTTPException(status_code=500, detail=str(e))

