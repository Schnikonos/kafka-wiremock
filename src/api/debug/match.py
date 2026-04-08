"""
Debug endpoint for rule matching analysis.
"""
import logging
import json
from typing import Dict, Any, Union, Optional
from fastapi import APIRouter, HTTPException, Body

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug", tags=["debug"])

# Global reference - will be set by main.py
_config_loader = None


def set_config_loader(loader):
    """Set the global config loader reference."""
    global _config_loader
    _config_loader = loader


@router.post("/match")
async def debug_match(
    topic: str = Body(..., description="Kafka topic name"),
    payload: Union[str, dict] = Body(..., description="Message payload (JSON)"),
    rule_name: Optional[str] = Body(None, description="Specific rule name to test (optional, tests all if omitted)")
) -> Dict[str, Any]:
    """
    Debug endpoint: Test message matching against rules and show detailed analysis.

    Args:
        topic: Topic name
        payload: Message content (as JSON dict or string)
        rule_name: Optional specific rule to test

    Returns:
        Detailed matching analysis including which conditions matched/failed
    """
    try:
        if not _config_loader:
            raise HTTPException(status_code=503, detail="Config loader not initialized")

        # Parse payload if string
        if isinstance(payload, str):
            payload = json.loads(payload)

        # Get rules for this topic
        rules = _config_loader.get_rules_for_topic(topic)

        if not rules:
            return {
                "success": True,
                "topic": topic,
                "message_preview": str(payload)[:200],
                "result": "NO_RULES",
                "message": "No rules configured for this topic",
                "rules_evaluated": 0
            }

        # Filter by rule name if specified
        if rule_name:
            rules = [r for r in rules if r.rule_name == rule_name]
            if not rules:
                return {
                    "success": False,
                    "error": f"Rule '{rule_name}' not found",
                    "topic": topic
                }

        # Evaluate each rule
        rule_results = []
        first_match = None

        for rule in rules:
            # Test each condition
            condition_details = []
            rule_matches = True

            if not rule.conditions:
                # Wildcard rule
                rule_matches = True
            else:
                for cond_idx, condition in enumerate(rule.conditions):
                    try:
                        from ...rules.matcher import MatcherFactory
                        matcher = MatcherFactory.create(condition.type)

                        if condition.type == 'jsonpath':
                            match_condition = {
                                'path': condition.expression,
                                'value': condition.value,
                                'regex': condition.regex
                            }
                        else:
                            match_condition = condition.regex if condition.regex else condition.value

                        result = matcher.match(payload, match_condition)

                        condition_details.append({
                            "index": cond_idx,
                            "type": condition.type,
                            "expression": condition.expression,
                            "value": condition.value,
                            "regex": condition.regex,
                            "matched": result.matched,
                            "context": result.context
                        })

                        if not result.matched:
                            rule_matches = False

                    except Exception as e:
                        logger.error(f"Error evaluating condition {cond_idx}: {e}")
                        condition_details.append({
                            "index": cond_idx,
                            "error": str(e),
                            "matched": False
                        })
                        rule_matches = False

            rule_result = {
                "rule_name": rule.rule_name,
                "priority": rule.priority,
                "matched": rule_matches,
                "conditions": condition_details,
                "conditions_count": len(rule.conditions),
                "outputs_count": len(rule.outputs),
                "output_topics": [o.topic for o in rule.outputs]
            }
            rule_results.append(rule_result)

            if rule_matches and first_match is None:
                first_match = rule_result

        return {
            "success": True,
            "topic": topic,
            "message_preview": str(payload)[:300],
            "total_rules": len(rules),
            "first_match": first_match,
            "all_rules": rule_results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in debug match: {e}")
        return {
            "success": False,
            "error": str(e),
            "topic": topic
        }

