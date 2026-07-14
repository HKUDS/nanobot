"""Post-run notification evaluation for heartbeat checks.

After heartbeat executes an internal check, this module makes a lightweight
LLM call to decide whether the result warrants notifying the user.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.utils.helpers import truncate_text
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

# Cap for a workspace-local heartbeat evaluator prompt override.
EVALUATOR_PROMPT_MAX_CHARS = 32_000


def evaluator_prompt_file(workspace: Path) -> Path:
    """Path to the workspace-local heartbeat evaluator prompt override."""
    return workspace / "prompts" / "evaluator.md"


def has_evaluator_prompt_override(workspace: Path) -> bool:
    """True when the workspace defines a non-empty evaluator prompt override."""
    with suppress(OSError):
        path = evaluator_prompt_file(workspace)
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())
    return False


def default_evaluator_prompt() -> str:
    """The built-in heartbeat notification-gate system prompt."""
    return render_template("agent/evaluator.md", part="system", strip=True)


def resolve_evaluator_prompt(workspace: Path) -> str:
    """Return the active evaluator prompt: workspace override or built-in default.

    Oversized overrides are truncated so a runaway file cannot blow up the
    evaluator call.
    """
    with suppress(OSError):
        text = evaluator_prompt_file(workspace).read_text(encoding="utf-8").rstrip()
        if text:
            if len(text) > EVALUATOR_PROMPT_MAX_CHARS:
                logger.warning(
                    "Workspace heartbeat evaluator prompt exceeds {} chars ({}); truncating.",
                    EVALUATOR_PROMPT_MAX_CHARS, len(text),
                )
                return truncate_text(text, EVALUATOR_PROMPT_MAX_CHARS)
            return text
    return default_evaluator_prompt()

_EVALUATE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_notification",
            "description": "Decide whether the user should be notified about this background task result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "should_notify": {
                        "type": "boolean",
                        "description": "true = result contains actionable/important info the user should see; false = routine or empty, safe to suppress",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One-sentence reason for the decision",
                    },
                },
                "required": ["should_notify"],
            },
        },
    }
]

async def evaluate_response(
    response: str,
    task_context: str,
    provider: LLMProvider,
    model: str,
    evaluator_prompt: str,
    default_notify: bool = False,
) -> bool:
    """Decide whether a heartbeat result should be delivered to the user.

    On any failure, falls back to ``default_notify``. Heartbeat passes
    ``False`` to fail closed.
    """

    try:
        llm_response = await provider.chat_with_retry(
            messages=[
                {"role": "system", "content": evaluator_prompt},
                {"role": "user", "content": render_template(
                    "agent/evaluator.md",
                    part="user",
                    task_context=task_context,
                    response=response,
                )},
            ],
            tools=_EVALUATE_TOOL,
            model=model,
            max_tokens=4096,
            temperature=0.0,
        )

        if not llm_response.should_execute_tools:
            if llm_response.has_tool_calls:
                logger.warning(
                    "evaluate_response: ignoring tool calls under finish_reason='{}', "
                    "defaulting to notify={}",
                    llm_response.finish_reason,
                    default_notify,
                )
            else:
                logger.warning(
                    "evaluate_response: no tool call returned, defaulting to notify={}",
                    default_notify,
                )
            return default_notify

        args = llm_response.tool_calls[0].arguments
        should_notify = args.get("should_notify", default_notify)
        reason = args.get("reason", "")
        logger.info("evaluate_response: should_notify={}, reason={}", should_notify, reason)
        return bool(should_notify)

    except Exception:
        logger.exception("evaluate_response failed, defaulting to notify={}", default_notify)
        return default_notify
