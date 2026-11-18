from __future__ import annotations

import base64
import binascii
import re
from functools import cache
from typing import Any, TypeGuard

from nanobot.channels.registry import discover_plugins

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


_CHANNEL_CHAT_PREFIX = "channel."
_MAX_CHANNEL_KEY_CHARS = 512
_CHANNEL_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,2731}")


@cache
def _channel_titles() -> dict[str, tuple[str, bool]]:
    # Descriptors are available even when the channel is disconnected or its SDK is absent.
    return {
        name: (plugin.display_name, plugin.management.multi_instance)
        for name, plugin in discover_plugins().items() if name != "websocket"
    }


def _runtime_channel_title(channel: str) -> str | None:
    name, separator, instance = channel.partition(".")
    descriptor = _channel_titles().get(name)
    if descriptor is None:
        return None
    title, multi_instance = descriptor
    return title if not separator or (multi_instance and instance) else None


def channel_session_title(session_key: str) -> str | None:
    channel, _, address = session_key.partition(":")
    if not address or len(session_key) > _MAX_CHANNEL_KEY_CHARS or not session_key.isprintable():
        return None
    return _runtime_channel_title(channel)


def entry_channel_title(channel: object) -> str | None:
    if channel == "webui":
        return "WebUI"
    return _runtime_channel_title(channel) if isinstance(channel, str) else None


def channel_session_chat_id(session_key: str) -> str | None:
    if channel_session_title(session_key) is None:
        return None
    encoded = base64.urlsafe_b64encode(session_key.encode("utf-8")).decode("ascii").rstrip("=")
    return _CHANNEL_CHAT_PREFIX + encoded


def channel_session_key(chat_id: object) -> str | None:
    """Decode the reference, not authorization to open or execute the session."""
    if not isinstance(chat_id, str) or not chat_id.startswith(_CHANNEL_CHAT_PREFIX):
        return None
    token = chat_id[len(_CHANNEL_CHAT_PREFIX):]
    if _CHANNEL_TOKEN_RE.fullmatch(token) is None:
        return None
    try:
        key = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    return key if channel_session_chat_id(key) == chat_id else None


def webui_display_session_key(chat_id: str) -> str:
    """Use only with a chat ID already admitted by the gateway."""
    return channel_session_key(chat_id) or webui_session_key(chat_id)
