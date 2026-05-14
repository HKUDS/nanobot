"""Helpers for WebUI chat title generation."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager
from nanobot.utils.helpers import truncate_text

WEBUI_SESSION_METADATA_KEY = "webui"
WEBUI_TITLE_METADATA_KEY = "title"
WEBUI_TITLE_USER_EDITED_METADATA_KEY = "title_user_edited"
TITLE_MAX_CHARS = 60


def mark_webui_session(session: Session, metadata: dict[str, Any]) -> bool:
    """Persist a WebUI marker only when the inbound websocket frame opted in."""
    if metadata.get(WEBUI_SESSION_METADATA_KEY) is not True:
        return False
    session.metadata[WEBUI_SESSION_METADATA_KEY] = True
    return True


def clean_generated_title(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\s*(title|标题)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().strip("\"'`“”‘’")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip("。.!！?？,，;；:")
    if len(text) > TITLE_MAX_CHARS:
        text = text[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return text


def _title_inputs(session: Session) -> tuple[str, str]:
    user_text = ""
    assistant_text = ""
    for message in session.messages:
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if role == "user" and not user_text:
            user_text = content.strip()
        elif role == "assistant" and not assistant_text:
            assistant_text = content.strip()
        if user_text and assistant_text:
            break
    return user_text, assistant_text


async def maybe_generate_webui_title(
    *,
    sessions: SessionManager,
    session_key: str,
    provider: LLMProvider,
    model: str,
) -> bool:
    """Generate and persist a short title for WebUI-owned sessions only."""
    session = sessions.get_or_create(session_key)
    if session.metadata.get(WEBUI_SESSION_METADATA_KEY) is not True:
        return False
    if session.metadata.get(WEBUI_TITLE_USER_EDITED_METADATA_KEY) is True:
        return False
    current_title = session.metadata.get(WEBUI_TITLE_METADATA_KEY)
    if isinstance(current_title, str) and current_title.strip():
        return False

    user_text, assistant_text = _title_inputs(session)
    if not user_text:
        return False

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
        response = await provider.chat_with_retry(
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
            max_tokens=32,
            temperature=0.2,
            retry_mode="standard",
        )
    except Exception:
        logger.debug("Failed to generate webui session title for {}", session_key, exc_info=True)
        return False

    title = clean_generated_title(response.content)
    if not title or title.lower().startswith("error"):
        return False
    session.metadata[WEBUI_TITLE_METADATA_KEY] = title
    sessions.save(session)
    return True


async def maybe_generate_webui_title_after_turn(
    *,
    channel: str,
    metadata: dict[str, Any],
    sessions: SessionManager,
    session_key: str,
    provider: LLMProvider,
    model: str,
) -> bool:
    if channel != "websocket" or metadata.get(WEBUI_SESSION_METADATA_KEY) is not True:
        return False
    return await maybe_generate_webui_title(
        sessions=sessions,
        session_key=session_key,
        provider=provider,
        model=model,
    )
