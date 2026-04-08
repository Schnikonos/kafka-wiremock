"""
Debug endpoint for template rendering.
"""
import logging
import re
from typing import Dict, Any
from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug", tags=["debug"])


@router.post("/template/render")
async def render_template(
    template: str = Body(..., description="Template string with placeholders"),
    context: Dict[str, Any] = Body({}, description="Context dictionary for placeholder substitution")
) -> Dict[str, Any]:
    """
    Debug endpoint: Render a template with provided context.

    Args:
        template: Template string (e.g., '{"id": "{{uuid}}", "now": "{{now}}", "field": "{{$.myField}}"}')
        context: Context dictionary with values to substitute

    Returns:
        Rendered template and available/used placeholders
    """
    try:
        from ...rules.templater import TemplateRenderer

        # Render the template
        rendered = TemplateRenderer.render(template, context)

        # Extract placeholders from template to show what was available/used
        placeholder_pattern = re.compile(r'\{\{[\s]*([a-zA-Z0-9_.$\[\](),\-+]+)[\s]*\}\}')
        found_placeholders = placeholder_pattern.findall(template)

        return {
            "success": True,
            "template": template,
            "rendered": rendered,
            "placeholders_found": found_placeholders,
            "context_keys": list(context.keys()),
            "template_length": len(template),
            "rendered_length": len(rendered)
        }
    except Exception as e:
        logger.error(f"Error rendering template: {e}")
        return {
            "success": False,
            "error": str(e),
            "template": template
        }

