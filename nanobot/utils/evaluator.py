"""Post-run notification evaluation for heartbeat checks.

After heartbeat executes an internal check, this module makes a lightweight
LLM call to decide whether the result warrants notifying the user.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from nanobot.utils.prompt_templates import render_template

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

async def evaluate_response(
    response: str,
    task_context: str,
    provider: LLMProvider,
    model: str,
    default_notify: bool = True,
) -> bool:
    """Decide whether a heartbeat result should be delivered to the user.

    On any failure, falls back to ``default_notify``. Heartbeat passes
    ``False`` to fail closed.
    """
    try:
        llm_response = await provider.chat_with_retry(
            messages=[
                {"role": "system", "content": render_template("agent/evaluator.md", part="system")},
                {"role": "user", "content": render_template(
                    "agent/evaluator.md",
                    part="user",
                    task_context=task_context,
                    response=response,
                )},
            ],
            tools=_EVALUATE_TOOL,
            model=model,
            max_tokens=256,
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
