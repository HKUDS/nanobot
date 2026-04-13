"""Post-run evaluation for background tasks (heartbeat & cron).

After the agent executes a background task, this module makes a lightweight
LLM call to decide whether the result warrants notifying the user.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from nanobot.agent.subagent_result import SubagentResult

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

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

_SYSTEM_PROMPT = (
    "You are a notification gate for a background agent. "
    "You will be given the original task and the agent's response. "
    "Call the evaluate_notification tool to decide whether the user "
    "should be notified.\n\n"
    "Notify when the response contains actionable information, errors, "
    "completed deliverables, or anything the user explicitly asked to "
    "be reminded about.\n\n"
    "Suppress when the response is a routine status check with nothing "
    "new, a confirmation that everything is normal, or essentially empty."
)


async def evaluate_response(
    response: str,
    task_context: str,
    provider: LLMProvider,
    model: str,
    result_payload: dict | None = None,
) -> bool:
    """Decide whether a background-task result should be delivered to the user.

    Uses a lightweight tool-call LLM request (same pattern as heartbeat
    ``_decide()``).  Falls back to ``True`` (notify) on any failure so
    that important messages are never silently dropped.
    """
    try:
        if isinstance(result_payload, dict):
            structured = SubagentResult.from_payload(result_payload)
            fast_path = _evaluate_structured_result(structured)
            if fast_path is not None:
                logger.info(
                    "evaluate_response: structured fast-path should_notify={} status={}",
                    fast_path,
                    structured.status,
                )
                return fast_path

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
            logger.warning("evaluate_response: no tool call returned, defaulting to notify")
            return True

        args = llm_response.tool_calls[0].arguments
        should_notify = args.get("should_notify", True)
        reason = args.get("reason", "")
        logger.info("evaluate_response: should_notify={}, reason={}", should_notify, reason)
        return bool(should_notify)

    except Exception:
        logger.exception("evaluate_response failed, defaulting to notify")
        return True


def _evaluate_structured_result(result: SubagentResult) -> bool | None:
    """Return a deterministic notify decision when the structured result is clear."""
    if result.status in {"error", "timeout", "cancelled"}:
        return True
    if result.status == "ok" and result.artifacts:
        return True
    if result.status == "ok" and not result.artifacts and not result.error:
        summary = result.summary.strip().lower()
        if summary in {
            "",
            "ok",
            "done",
            "all clear, no updates",
            "no updates",
            "nothing to report",
        }:
            return False
    return None
