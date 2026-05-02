"""``send_form`` tool — send a message with one or more pre-registered form modals.

Form templates are declared in nanobot.json under ``tools.forms.templates``. Each
template encodes a Discord-style modal (title + inputs) and the button that opens
it. The model invokes templates by ID; it never authors button or modal payloads
manually for these flows. This pattern removes paraphrasing failures (model rewrites
labels, drops fields, mismatches custom_ids) for any form whose shape is fixed.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.schema import (
    ArraySchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config.schema import FormTemplateConfig

_MAX_FORMS_PER_MESSAGE = 5  # Discord caps action rows; we use one row of buttons.


def _template_to_button(template: FormTemplateConfig) -> dict[str, Any]:
    """Render a FormTemplateConfig as a button-with-modal cell for the message tool."""
    inputs: list[dict[str, Any]] = []
    for inp in template.inputs:
        # `model_dump(exclude_none=True)` so unset fields fall back to channel defaults
        # (e.g. radio `required` defaults to True; select `min_values` defaults to 1).
        inputs.append(inp.model_dump(exclude_none=True, exclude_defaults=False))
    return {
        "type": "button",
        "label": template.button_label or template.title,
        "style": template.button_style,
        "custom_id": template.button_custom_id or template.id,
        "modal": {"title": template.title, "inputs": inputs},
    }


@tool_parameters(
    tool_parameters_schema(
        forms=ArraySchema(
            StringSchema("Form template ID registered under tools.forms.templates"),
            description=(
                "List of registered form template IDs to attach to the message. "
                "Renders as one row of buttons (max 5). Each button opens the "
                "template's modal when clicked."
            ),
        ),
        content=StringSchema(
            "Message body shown above the form buttons. Required by Discord — "
            "for a standalone form prompt with no narrative, pass a one-liner."
        ),
        channel=StringSchema("Optional: target channel (defaults to current conversation)"),
        chat_id=StringSchema("Optional: target chat/user ID (defaults to current conversation)"),
        required=["forms", "content"],
    )
)
class SendFormTool(Tool):
    """Send a message with one or more registered form modals attached."""

    def __init__(
        self,
        message_tool: MessageTool,
        templates: list[FormTemplateConfig] | None = None,
    ) -> None:
        self._message_tool = message_tool
        self._registry: dict[str, FormTemplateConfig] = {}
        for tpl in templates or []:
            if tpl.id in self._registry:
                logger.warning("send_form: duplicate template id {!r}; later wins", tpl.id)
            self._registry[tpl.id] = tpl

    @property
    def name(self) -> str:
        return "send_form"

    @property
    def description(self) -> str:
        if not self._registry:
            return (
                "Send a message with a registered form modal attached. "
                "No templates are currently registered — define them under "
                "tools.forms.templates in nanobot.json before using this tool."
            )
        ids = sorted(self._registry)
        return (
            "Send a message with one or more pre-registered form modals attached. "
            "USE THIS for any flow whose form shape is fixed (daily check-ins, "
            "feedback forms, structured surveys, etc.) — never construct buttons "
            "or modal payloads manually for these flows. The labels, options, and "
            "custom_ids are baked into the template, so the receiving skill can "
            "rely on stable field identifiers in the submission. "
            f"Available template IDs: {', '.join(ids)}. Pass `forms` as a list of "
            "those IDs (max 5 per message; renders as one row of buttons) and "
            "`content` as the message body shown above the buttons."
        )

    async def execute(
        self,
        forms: list[str] | None = None,
        content: str = "",
        channel: str = "",
        chat_id: str = "",
    ) -> str:
        if not self._registry:
            return (
                "Error: send_form has no templates registered. Add entries under "
                "tools.forms.templates in nanobot.json before calling this tool."
            )
        if not isinstance(forms, list) or not forms:
            return "Error: `forms` must be a non-empty list of template IDs."
        if len(forms) > _MAX_FORMS_PER_MESSAGE:
            return (
                f"Error: too many forms ({len(forms)}); max {_MAX_FORMS_PER_MESSAGE} "
                "per message (one Discord action row)."
            )
        if not isinstance(content, str) or not content.strip():
            return "Error: `content` is required (Discord drops empty-content messages)."
        unknown = [fid for fid in forms if fid not in self._registry]
        if unknown:
            available = ", ".join(sorted(self._registry))
            return (
                f"Error: unknown form template id(s): {', '.join(unknown)}. "
                f"Available: {available}."
            )

        row = [_template_to_button(self._registry[fid]) for fid in forms]
        return await self._message_tool.execute(
            content=content,
            channel=channel,
            chat_id=chat_id,
            buttons=[row],
        )
