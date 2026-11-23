from __future__ import annotations

HEARTBEAT_SESSION_KEY = "heartbeat"


def is_dream_session(key: str) -> bool:
    """Identify the per-run session namespace owned by Dream."""
    return key.startswith("dream:")


def is_internal_session(key: str) -> bool:
    """Identify maintenance sessions whose context is not a user conversation."""
    return key == HEARTBEAT_SESSION_KEY or is_dream_session(key)
