"""Shared session key constants and helpers."""

from __future__ import annotations

UNIFIED_SESSION_KEY = "unified:default"


def session_key_for_channel(channel: str, chat_id: str, *, unified_session: bool = False) -> str:
    """Return the session key for a channel/chat pair."""
    if unified_session:
        return UNIFIED_SESSION_KEY
    return f"{channel}:{chat_id}"
