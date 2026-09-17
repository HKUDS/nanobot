"""Metadata carried by user input sent between persisted sessions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, TypedDict, cast

from nanobot.session.session_handles import normalize_session_handle

SESSION_MESSAGE_METADATA_KEY = "_session_message"

_MAX_SESSION_KEY_CHARS = 512
_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class SessionMessageEnvelope(TypedDict):
    message_id: str
    created_at_ms: int
    expect_reply: bool
    source_handle: str
    source_session_key: str
    target_session_key: str


def session_message_envelope(
    metadata: Mapping[str, Any] | None,
) -> SessionMessageEnvelope | None:
    """Read a validated envelope from request or persisted-message metadata."""
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get(SESSION_MESSAGE_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return None
    data = cast(Mapping[str, object], raw)
    message_id = data.get("message_id")
    created_at_ms = data.get("created_at_ms")
    expect_reply = data.get("expect_reply")
    source_handle_value = data.get("source_handle")
    source_session_key = _session_key(data.get("source_session_key"))
    target_session_key = _session_key(data.get("target_session_key"))
    try:
        source_handle = (
            normalize_session_handle(source_handle_value)
            if isinstance(source_handle_value, str)
            else None
        )
    except ValueError:
        source_handle = None
    if (
        not isinstance(message_id, str)
        or _MESSAGE_ID_RE.fullmatch(message_id) is None
        or not isinstance(created_at_ms, int)
        or isinstance(created_at_ms, bool)
        or created_at_ms < 0
        or not isinstance(expect_reply, bool)
        or source_handle is None
        or source_session_key is None
        or target_session_key is None
    ):
        return None
    return {
        "message_id": message_id,
        "created_at_ms": created_at_ms,
        "expect_reply": expect_reply,
        "source_handle": source_handle,
        "source_session_key": source_session_key,
        "target_session_key": target_session_key,
    }


def _session_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized_key = value.strip()
    if not normalized_key or len(normalized_key) > _MAX_SESSION_KEY_CHARS:
        return None
    return normalized_key
