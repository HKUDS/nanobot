"""Pairing store for DM sender approval.

Persistent storage at ``~/.nanobot/pairing.json`` keeps approved senders
and pending pairing codes per channel.  The store is designed for
private-assistant scale: small JSON file, simple locking, no external DB.
"""

from __future__ import annotations

import json
import secrets
import string
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_data_dir

_LOCK = threading.Lock()
_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 6  # e.g. XK9-42F
_TTL_DEFAULT_S = 600  # 10 minutes


def _store_path() -> Path:
    return get_data_dir() / "pairing.json"


def _load() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {"approved": {}, "pending": {}}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupted pairing store, resetting")
        return {"approved": {}, "pending": {}}


def _save(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
    tmp.replace(path)


def _gc_pending(data: dict[str, Any]) -> None:
    """Remove expired pending entries in-place."""
    now = time.time()
    pending: dict[str, Any] = data.get("pending", {})
    expired = [code for code, info in pending.items() if info.get("expires_at", 0) < now]
    for code in expired:
        del pending[code]


def generate_code(
    channel: str,
    sender_id: str,
    ttl: int = _TTL_DEFAULT_S,
) -> str:
    """Create a new pairing code for *sender_id* on *channel*.

    Returns the code (e.g. ``"XK9-42F"``).
    """
    with _LOCK:
        data = _load()
        _gc_pending(data)
        # Ensure uniqueness
        for _ in range(100):
            raw = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
            code = f"{raw[:3]}-{raw[3:]}"
            if code not in data.get("pending", {}):
                break
        else:  # pragma: no cover
            raise RuntimeError("Failed to generate unique pairing code")

        data.setdefault("pending", {})[code] = {
            "channel": channel,
            "sender_id": sender_id,
            "created_at": time.time(),
            "expires_at": time.time() + ttl,
        }
        _save(data)
        logger.info("Generated pairing code {} for {}@{}", code, sender_id, channel)
        return code


def approve_code(code: str) -> tuple[str, str] | None:
    """Approve a pending pairing code.

    Returns ``(channel, sender_id)`` on success, or ``None`` if the code
    does not exist or has expired.
    """
    with _LOCK:
        data = _load()
        _gc_pending(data)
        pending: dict[str, Any] = data.get("pending", {})
        info = pending.pop(code, None)
        if info is None:
            return None
        channel = info["channel"]
        sender_id = info["sender_id"]
        data.setdefault("approved", {}).setdefault(channel, []).append(sender_id)
        _save(data)
        logger.info("Approved pairing code {} for {}@{}", code, sender_id, channel)
        return channel, sender_id


def deny_code(code: str) -> bool:
    """Reject and discard a pending pairing code.

    Returns ``True`` if the code existed and was removed.
    """
    with _LOCK:
        data = _load()
        _gc_pending(data)
        pending: dict[str, Any] = data.get("pending", {})
        if code in pending:
            del pending[code]
            _save(data)
            logger.info("Denied pairing code {}", code)
            return True
        return False


def is_approved(channel: str, sender_id: str) -> bool:
    """Check whether *sender_id* has been approved on *channel*."""
    with _LOCK:
        data = _load()
        approved: dict[str, list[str]] = data.get("approved", {})
        return str(sender_id) in approved.get(channel, [])


def list_pending() -> list[dict[str, Any]]:
    """Return all non-expired pending pairing requests."""
    with _LOCK:
        data = _load()
        _gc_pending(data)
        return [
            {"code": code, **info}
            for code, info in data.get("pending", {}).items()
        ]


def revoke(channel: str, sender_id: str) -> bool:
    """Remove an approved sender from *channel*.

    Returns ``True`` if the sender was present and removed.
    """
    with _LOCK:
        data = _load()
        approved: dict[str, list[str]] = data.get("approved", {})
        lst = approved.get(channel, [])
        if sender_id in lst:
            lst.remove(sender_id)
            if not lst:
                del approved[channel]
            _save(data)
            logger.info("Revoked {} from {}", sender_id, channel)
            return True
        return False


def get_approved(channel: str) -> list[str]:
    """Return all approved sender IDs for *channel*."""
    with _LOCK:
        data = _load()
        return list(data.get("approved", {}).get(channel, []))
