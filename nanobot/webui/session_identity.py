"""Stable mapping between public WebUI chat IDs and persisted session keys."""

from __future__ import annotations

import re
from typing import Any, TypeGuard

WEBUI_SESSION_STORAGE_PREFIX = "websocket:"
_WEBUI_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")


def is_valid_webui_chat_id(value: Any) -> TypeGuard[str]:
    """Validate the compact chat IDs accepted by the WebUI protocol."""
    return isinstance(value, str) and _WEBUI_CHAT_ID_RE.fullmatch(value) is not None


def webui_session_key(chat_id: str) -> str:
    """Return the backward-compatible persisted key for a WebUI chat."""
    return f"{WEBUI_SESSION_STORAGE_PREFIX}{chat_id}"


def is_webui_session_key(session_key: str) -> bool:
    """Return whether *session_key* belongs to the WebUI session namespace."""
    return session_key.startswith(WEBUI_SESSION_STORAGE_PREFIX)


def webui_chat_id(session_key: str) -> str | None:
    """Extract a non-empty WebUI chat ID from a persisted session key."""
    if not is_webui_session_key(session_key):
        return None
    chat_id = session_key.removeprefix(WEBUI_SESSION_STORAGE_PREFIX)
    return chat_id or None
