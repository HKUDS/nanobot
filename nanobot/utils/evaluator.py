"""Post-run evaluation for background tasks (heartbeat & cron)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

EvaluationLevel = Literal["normal", "error"]
NotificationLevel = Literal["all", "error", "silent"]

_EVALUATE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_background_result",
            "description": "Classify the result of a background task as normal or error.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["normal", "error"],
                        "description": "Return 'error' for failures, broken checks, blocked work, or anything requiring attention. Return 'normal' for routine, successful, or informational results.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One-sentence reason for the classification",
                    },
                },
                "required": ["level"],
            },
        },
    }
]

_SYSTEM_PROMPT = (
    "You are a classifier for background agent results. "
    "You will be given the original task and the agent's response. "
    "You must call the evaluate_background_result tool and return exactly one level.\n\n"
    "Return level='error' when the response reports a failure, problem, exception, blocked work, bad status, or anything that needs attention.\n"
    "Return level='normal' when the response is successful, routine, informational, empty, or says everything is fine.\n\n"
    "Do not decide whether to notify. Only classify the result as 'normal' or 'error'."
)


async def evaluate_response(
    response: str,
    task_context: str,
    provider: LLMProvider,
    model: str,
) -> EvaluationLevel:
    """Classify a background-task result as ``normal`` or ``error``.

    Uses a lightweight tool-call LLM request (same pattern as heartbeat
    ``_decide()``). Falls back to ``error`` on any failure so important
    messages are never silently downgraded.
    """
    try:
        llm_response = await provider.chat_with_retry(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"## Original task\n{task_context}\n\n"
                    f"## Agent response\n{response}"
                )},
            ],
            tools=_EVALUATE_TOOL,
            model=model,
            max_tokens=256,
            temperature=0.0,
        )

        if not llm_response.has_tool_calls:
            logger.warning("evaluate_response: no tool call returned, defaulting to error")
            return "error"

        args = llm_response.tool_calls[0].arguments
        level = args.get("level", "error")
        reason = args.get("reason", "")
        if level not in {"normal", "error"}:
            logger.warning("evaluate_response: invalid level '{}', defaulting to error", level)
            return "error"
        logger.info("evaluate_response: level={}, reason={}", level, reason)
        return level

    except Exception:
        logger.exception("evaluate_response failed, defaulting to error")
        return "error"


def should_publish(level: EvaluationLevel, policy: NotificationLevel) -> bool:
    """Apply config policy to an evaluator result."""
    if policy == "silent":
        return False
    if policy == "error":
        return level == "error"
    return True
