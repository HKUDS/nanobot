"""Post-response follow-up evaluation.

After the agent responds to a user message, this module makes a lightweight
LLM call to decide whether asking a follow-up question would enrich the
conversation.  The pattern mirrors ``nanobot.utils.evaluator``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_FOLLOW_UP_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "follow_up_decision",
            "description": "Decide whether to ask the user a follow-up question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "should_ask": {
                        "type": "boolean",
                        "description": (
                            "true = the conversation would genuinely benefit from "
                            "a follow-up question; false = let the user lead"
                        ),
                    },
                    "question": {
                        "type": "string",
                        "description": (
                            "A natural, conversational follow-up question "
                            "(only when should_ask is true)"
                        ),
                    },
                },
                "required": ["should_ask"],
            },
        },
    }
]

_SYSTEM_PROMPT = (
    "You are a conversational follow-up evaluator. Given a conversation "
    "between a user and an assistant, decide whether asking a follow-up "
    "question would make the conversation more engaging and helpful.\n\n"
    "Ask a follow-up when:\n"
    "- The user's topic has unexplored depth worth discussing\n"
    "- The assistant's response naturally leads to a related question\n"
    "- The user seems engaged and might appreciate continued dialogue\n"
    "- There is a practical next step the user might want help with\n\n"
    "Do NOT ask a follow-up when:\n"
    "- The conversation is a simple, transactional exchange (e.g. 'what time is it')\n"
    "- The user gave a clear closing signal (e.g. 'thanks', 'got it')\n"
    "- The question would feel forced or repetitive\n"
    "- The assistant already asked a question in its response\n\n"
    "The follow-up question should feel natural, not like a survey. "
    "Keep it short and conversational."
)


async def evaluate_follow_up(
    conversation_tail: str,
    last_response: str,
    provider: LLMProvider,
    model: str,
) -> tuple[bool, str | None]:
    """Decide whether a follow-up question is appropriate.

    Uses a lightweight tool-call LLM request (same pattern as
    ``evaluate_response`` in ``nanobot.utils.evaluator``).

    Returns:
        (should_ask, question_text) — question_text is ``None`` when
        ``should_ask`` is ``False``.
    """
    try:
        llm_response = await provider.chat_with_retry(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"## Recent conversation\n{conversation_tail}\n\n"
                    f"## Last assistant response\n{last_response}"
                )},
            ],
            tools=_FOLLOW_UP_TOOL,
            model=model,
            max_tokens=256,
            temperature=0.7,
        )

        if not llm_response.has_tool_calls:
            logger.debug("follow_up: no tool call returned, skipping")
            return False, None

        args = llm_response.tool_calls[0].arguments
        should_ask = args.get("should_ask", False)
        question = args.get("question")
        logger.info(
            "follow_up: should_ask={}, question={}",
            should_ask,
            (question[:60] + "...") if question and len(question) > 60 else question,
        )
        return bool(should_ask), question if should_ask else None

    except Exception:
        logger.exception("follow_up evaluation failed, skipping")
        return False, None
