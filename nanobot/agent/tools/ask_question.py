"""Structured clarification tool for collecting user choices."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool


class AskQuestionTool(Tool):
    """Ask structured multiple-choice questions to reduce ambiguity."""

    name = "ask_question"
    description = (
        "Ask the user one or more multiple-choice questions with option IDs. "
        "Use this to clarify ambiguous requirements before acting."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Optional short heading for the question set",
            },
            "questions": {
                "type": "array",
                "description": "List of questions to ask",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Question ID"},
                        "prompt": {"type": "string", "description": "Question text"},
                        "allow_multiple": {
                            "type": "boolean",
                            "description": "Whether multiple options can be selected",
                        },
                        "options": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "description": "Option ID"},
                                    "label": {
                                        "type": "string",
                                        "description": "Human-readable option text",
                                    },
                                },
                                "required": ["id", "label"],
                            },
                        },
                    },
                    "required": ["id", "prompt", "options"],
                },
            },
        },
        "required": ["questions"],
    }

    async def execute(
        self,
        questions: list[dict[str, Any]],
        title: str | None = None,
        **kwargs: Any,
    ) -> str:
        if not questions:
            return "Error: questions must not be empty"

        lines: list[str] = []
        if title:
            lines.append(title.strip())
            lines.append("")

        for idx, q in enumerate(questions, 1):
            qid = str(q.get("id", f"q{idx}"))
            prompt = str(q.get("prompt", "")).strip()
            options = q.get("options") or []
            if not prompt:
                return f"Error: question '{qid}' has empty prompt"
            if not isinstance(options, list) or len(options) < 2:
                return f"Error: question '{qid}' must include at least 2 options"

            allow_multiple = bool(q.get("allow_multiple", False))
            mode = "multiple" if allow_multiple else "single"
            lines.append(f"Q{idx} ({qid}) [{mode}]: {prompt}")
            for opt in options:
                oid = str(opt.get("id", "")).strip()
                label = str(opt.get("label", "")).strip()
                if not oid or not label:
                    return f"Error: question '{qid}' has invalid option id/label"
                lines.append(f"- {oid}: {label}")
            lines.append("")

        lines.append("Reply with selected option IDs.")
        lines.append("Format example: q1=a,q2=b|c")
        return "\n".join(lines).strip()
