"""
Rules management endpoints.
"""
import logging
import json
from typing import Dict, Any, Optional, Union, List
from fastapi import APIRouter, HTTPException, Query, Body

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["rules"])

# Global references - will be set by main.py
_config_loader = None
_listener_engine = None


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
    message: Union[Dict[str, Any], str] = Body(..., description="Message to test against rules")
) -> Dict[str, Any]:
    """
    Dry-run endpoint: Show which rule would match a message and why.

    Args:
        topic: Input topic for the message
        message: Message payload (JSON object or string)

    Returns:
        Matching rule details with matcher context and extraction results
    """
    if not _config_loader or not _listener_engine:
        raise HTTPException(status_code=503, detail="Services not initialized")

    try:
        # Get rules for the topic
        rules = _config_loader.get_rules_for_topic(topic)

        if not rules:
            return {
                "matched": False,
                "message": "No rules configured for this topic",
                "message_preview": str(message)[:200],
                "topic": topic,
                "evaluated_rules": 0
            }

        # Try to match each rule
        for rule in rules:
            match_result = _listener_engine.matcher_factory.match_rule(
                message=message,
                rule=rule
            )

            if match_result.matched:
                # Extract details about what matched
                conditions_detail = []
                for i, cond in enumerate(rule.conditions):
                    cond_match = match_result.context.get(f"condition_{i}")
                    conditions_detail.append({
                        "index": i,
                        "type": cond.type,
                        "expression": cond.expression,
                        "value": cond.value,
                        "regex": cond.regex,
                        "matched": cond_match is not None,
                        "extracted_context": dict(list(match_result.context.items())[i:i+1]) if cond_match else {}
                    })

                return {
                    "matched": True,
                    "rule": {
                        "name": rule.rule_name,
                        "priority": rule.priority,
                        "input_topic": rule.input_topic
                    },
                    "conditions": conditions_detail,
                    "context": match_result.context,
                    "message_preview": str(message)[:200],
                    "topic": topic,
                    "outputs_count": len(rule.outputs),
                    "outputs": [{"topic": o.topic, "delay_ms": o.delay_ms} for o in rule.outputs]
                }

        # No rule matched
        return {
            "matched": False,
            "message": "No rules matched this message",
            "message_preview": str(message)[:200],
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

