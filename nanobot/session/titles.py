"""Session title generation for title-capable channels (websocket, telegram)."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from nanobot.llm_usage.context import llm_usage_source
from nanobot.providers.base import LLMProvider
from nanobot.runtime_context import public_history_message
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.keys import WEBUI_SESSION_METADATA_KEY
from nanobot.session.manager import Session, SessionManager
from nanobot.utils.helpers import strip_think, truncate_text
from nanobot.utils.llm_runtime import LLMRuntime

TITLE_METADATA_KEY = "title"
TITLE_USER_EDITED_METADATA_KEY = "title_user_edited"
TITLE_MAX_CHARS = 60
TITLE_GENERATION_MAX_TOKENS = 96
TITLE_GENERATION_REASONING_EFFORT = "none"
# Channels whose chats get a generated session title; each generation is also
# announced to the originating chat as a ``SessionTitleEvent`` (Telegram) or a
# metadata refresh (WebUI).
TITLE_GENERATION_CHANNELS = frozenset({"websocket", "telegram"})


def validated_llm_runtime(value: object) -> LLMRuntime | None:
    """Keep runtime-event consumers defensive if an external publisher violates the contract."""
    return value if isinstance(value, LLMRuntime) else None


def clean_generated_title(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\s*(title|标题)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().strip("\"'`“”‘’")
    text = strip_think(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip("。.!！?？,，;；:")
    if len(text) > TITLE_MAX_CHARS:
        text = text[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return text


def _title_inputs(session: Session) -> tuple[str, str]:
    user_text = ""
    assistant_text = ""
    for message in session.messages:
        if message.get("_command") is True:
            continue
        if is_hidden_history_message(message):
            continue
        message = public_history_message(message)
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        content = strip_think(content)
        if not content:
            continue
        if role == "user" and not user_text:
            user_text = content.strip()
        elif role == "assistant" and not assistant_text:
            assistant_text = content.strip()
        if user_text and assistant_text:
            break
    return user_text, assistant_text


def _latest_title_inputs(session: Session) -> tuple[str, str]:
    """Latest user/assistant texts, for turns executed on a shared session."""
    user_text = ""
    assistant_text = ""
    for message in reversed(session.messages):
        if message.get("_command") is True:
            continue
        if is_hidden_history_message(message):
            continue
        message = public_history_message(message)
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        content = strip_think(content)
        if not content:
            continue
        if role == "user" and not user_text:
            user_text = content.strip()
        elif role == "assistant" and not assistant_text:
            assistant_text = content.strip()
        if user_text and assistant_text:
            break
    return user_text, assistant_text


async def maybe_generate_session_title(
    *,
    sessions: SessionManager,
    session_key: str,
    provider: LLMProvider,
    model: str,
    target_session_key: str | None = None,
    channel: str = "websocket",
) -> str | None:
    """Generate and persist a short title for a session owned by a title channel.

    ``session_key`` owns the conversation content. Under unified-session
    routing this is the shared session while WebUI renders per-chat sessions,
    so pass ``target_session_key`` to project the title onto that per-chat
    session instead of storing it on the shared one.

    Returns the generated title, or ``None`` when generation did not run.
    """
    if channel not in TITLE_GENERATION_CHANNELS:
        return None
    routed_session = sessions.get_or_create(session_key)
    target_is_routed = target_session_key is None or target_session_key == session_key
    if target_is_routed or target_session_key is None:
        target_session = routed_session
    else:
        target_session = sessions.get_or_create(target_session_key)
    if (
        channel == "websocket"
        and routed_session.metadata.get(WEBUI_SESSION_METADATA_KEY) is not True
        and target_session.metadata.get(WEBUI_SESSION_METADATA_KEY) is not True
    ):
        return None
    if target_session.metadata.get(TITLE_USER_EDITED_METADATA_KEY) is True:
        return None
    current_title = target_session.metadata.get(TITLE_METADATA_KEY)
    if isinstance(current_title, str) and current_title.strip():
        cleaned_current_title = clean_generated_title(current_title)
        if cleaned_current_title:
            if cleaned_current_title != current_title:
                target_session.metadata[TITLE_METADATA_KEY] = cleaned_current_title
                sessions.save(target_session)
            return None
        target_session.metadata.pop(TITLE_METADATA_KEY, None)

    if target_is_routed:
        user_text, assistant_text = _title_inputs(routed_session)
    else:
        # Shared-session content mixes every channel; generation runs right
        # after this turn, so its exchange is the latest pair.
        user_text, assistant_text = _latest_title_inputs(routed_session)
    if not user_text:
        return None

    prompt = (
        "Generate a concise title for this chat.\n"
        "Rules:\n"
        "- Use the same language as the user when practical.\n"
        "- 3 to 8 words.\n"
        "- No quotes.\n"
        "- No punctuation at the end.\n"
        "- Return only the title.\n\n"
        f"User: {truncate_text(user_text, 1_000)}"
    )
    if assistant_text:
        prompt += f"\nAssistant: {truncate_text(assistant_text, 1_000)}"

    try:
        with llm_usage_source("system"):
            response = await provider.chat_stream_with_retry(
                [
                    {
                        "role": "system",
                        "content": (
                            "You write short, neutral chat titles. "
                            "Return only the title text."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                model=model,
                max_tokens=TITLE_GENERATION_MAX_TOKENS,
                temperature=0.2,
                reasoning_effort=TITLE_GENERATION_REASONING_EFFORT,
                retry_mode="standard",
            )
    except Exception:
        logger.opt(exception=True).debug(
            "Failed to generate session title for {}", session_key
        )
        return None

    title = clean_generated_title(response.content)
    if not title or title.lower().startswith("error"):
        logger.debug(
            "Session title generation returned no usable title for {} (finish_reason={})",
            session_key,
            response.finish_reason,
        )
        return None
    # A manual rename may land while the title LLM call is in flight; both run
    # in this process against the same cached Session, so re-check the flag
    # before persisting to avoid clobbering the user-edited title.
    if target_session.metadata.get(TITLE_USER_EDITED_METADATA_KEY) is True:
        return None
    target_session.metadata[TITLE_METADATA_KEY] = title
    sessions.save(target_session)
    return title


async def maybe_generate_title_after_turn(
    *,
    channel: str,
    chat_id: str,
    metadata: dict[str, Any],
    sessions: SessionManager,
    session_key: str,
    provider: LLMProvider,
    model: str,
) -> str | None:
    """Generate a title for the chat that just finished a turn.

    WebUI sessions need the inbound ``webui`` opt-in marker; Telegram chats
    always participate so channel tooling can react to title generation.
    """
    if channel not in TITLE_GENERATION_CHANNELS:
        return None
    if channel == "websocket" and metadata.get(WEBUI_SESSION_METADATA_KEY) is not True:
        return None
    if channel == "telegram":
        # Telegram owns its topic-scoped session key; import lazily so this
        # module stays importable without the optional python-telegram-bot
        # dependency (the channel is always already loaded by the time
        # telegram title generation can run).
        from nanobot.channels.telegram.runtime import TelegramChannel

        origin_session_key = (
            TelegramChannel.derive_topic_session_key(
                chat_id, metadata.get("message_thread_id"),
            )
            or f"telegram:{chat_id}"
        )
    else:
        origin_session_key = f"{channel}:{chat_id}"
    return await maybe_generate_session_title(
        sessions=sessions,
        session_key=session_key,
        provider=provider,
        model=model,
        channel=channel,
        target_session_key=(
            origin_session_key if origin_session_key != session_key else None
        ),
    )
