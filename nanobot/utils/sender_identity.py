"""Normalize chat sender identity for model-visible context."""

from __future__ import annotations

import re
from typing import Any, Mapping

_MAX_IDENTITY_CHARS = 200
_SPACE_RE = re.compile(r"\s+")

SENDER_DISPLAY_NAME_KEY = "sender_display_name"
SENDER_USERNAME_KEY = "sender_username"
SENDER_ID_KEY = "sender_id"


def _clean_identity_value(value: Any) -> str | None:
    """Return a compact single-line identity value, or None when blank."""
    if value is None:
        return None
    text = _SPACE_RE.sub(" ", str(value).replace("\x00", "")).strip()
    if not text:
        return None
    if len(text) > _MAX_IDENTITY_CHARS:
        text = text[: _MAX_IDENTITY_CHARS - 1].rstrip() + "..."
    return text


def sender_session_extra(
    metadata: Mapping[str, Any] | None,
    *,
    sender_id: str | None = None,
) -> dict[str, str]:
    """Return normalized sender identity fields safe to persist in a session."""
    meta = metadata or {}
    extra: dict[str, str] = {}

    display_name = _clean_identity_value(meta.get(SENDER_DISPLAY_NAME_KEY))
    username = _clean_identity_value(meta.get(SENDER_USERNAME_KEY))
    clean_sender_id = _clean_identity_value(sender_id or meta.get(SENDER_ID_KEY))

    if clean_sender_id:
        extra[SENDER_ID_KEY] = clean_sender_id
    if display_name:
        extra[SENDER_DISPLAY_NAME_KEY] = display_name
    if username:
        extra[SENDER_USERNAME_KEY] = username
    return extra


def sender_runtime_lines(
    metadata: Mapping[str, Any] | None,
    *,
    sender_id: str | None = None,
) -> list[str]:
    """Return runtime context lines describing the sender."""
    extra = sender_session_extra(metadata, sender_id=sender_id)
    lines: list[str] = []
    if display_name := extra.get(SENDER_DISPLAY_NAME_KEY):
        lines.append(f"Sender Display Name: {display_name}")
    if username := extra.get(SENDER_USERNAME_KEY):
        lines.append(f"Sender Username: {username}")
    return lines


def sender_history_prefix(message: Mapping[str, Any]) -> str | None:
    """Return a compact sender prefix for replayed user turns."""
    extra = sender_session_extra(message)
    if not extra:
        return None

    parts: list[str] = []
    if display_name := extra.get(SENDER_DISPLAY_NAME_KEY):
        parts.append(f"display_name={display_name}")
    if username := extra.get(SENDER_USERNAME_KEY):
        parts.append(f"username={username}")
    if sender_id := extra.get(SENDER_ID_KEY):
        parts.append(f"id={sender_id}")
    return "[Message Sender: " + "; ".join(parts) + "]"


def annotate_user_content_with_sender(
    message: Mapping[str, Any],
    content: Any,
) -> Any:
    """Prepend sender identity metadata to a replayed user message."""
    prefix = sender_history_prefix(message)
    if not prefix:
        return content
    if isinstance(content, str):
        return f"{prefix}\n{content}" if content else prefix
    if isinstance(content, list):
        return [{"type": "text", "text": prefix}, *content]
    return content
