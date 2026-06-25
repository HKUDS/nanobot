"""Ask the user for missing or ambiguous requirements."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters

ASK_CLARIFICATION_TOOL_NAME = "ask_clarification"
CLARIFICATION_TYPES = [
    "missing_info",
    "ambiguous_requirement",
    "approach_choice",
    "risk_confirmation",
    "suggestion",
]


def format_clarification_question(
    question: str,
    *,
    context: str | None = None,
    options: list[str] | None = None,
) -> str:
    parts = [str(question).strip()]
    if context and context.strip():
        parts.append(context.strip())
    choices = [str(option).strip() for option in (options or []) if str(option).strip()]
    if choices:
        parts.append("Options:\n" + "\n".join(
            f"{index}. {option}" for index, option in enumerate(choices, start=1)
        ))
    return "\n\n".join(part for part in parts if part)


@tool_parameters({
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "Focused question to ask the user before continuing.",
            "minLength": 1,
        },
        "clarification_type": {
            "type": "string",
            "enum": CLARIFICATION_TYPES,
            "description": "Why clarification is needed.",
        },
        "context": {
            "type": "string",
            "description": "Optional short context explaining why the question matters.",
        },
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional answer choices to show the user.",
        },
    },
    "required": ["question", "clarification_type"],
    "additionalProperties": False,
})
class AskClarificationTool(Tool):
    """Ask a focused clarification question and end the current turn."""

    @property
    def name(self) -> str:
        return ASK_CLARIFICATION_TOOL_NAME

    @property
    def description(self) -> str:
        return (
            "Ask the user one focused clarification question when required information is "
            "missing, requirements are ambiguous, an approach choice is needed, or explicit "
            "confirmation is required before risky work."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        question: str,
        clarification_type: str,
        context: str | None = None,
        options: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        return format_clarification_question(question, context=context, options=options)
