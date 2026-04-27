"""Helpers for bridging SimpleX chats into nanobot's WebSocket channel."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_PROGRESS_KINDS = frozenset({"progress", "tool_hint"})
_STATE_STEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def default_simplex_state_path(name: str) -> Path:
    """Return a stable bridge state path for *name*."""
    stem = _STATE_STEM_RE.sub("-", name.strip()).strip("-") or "default"
    return Path.home() / ".nanobot" / "simplex-bridge" / f"{stem}.json"


def extract_simplex_reply_text(payload: dict[str, Any], *, chat_id: str) -> str | None:
    """Return outbound reply text to send into SimpleX, or ``None`` to ignore."""
    if payload.get("event") != "message":
        return None
    if payload.get("chat_id") != chat_id:
        return None
    if payload.get("kind") in _PROGRESS_KINDS:
        return None
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    return text
