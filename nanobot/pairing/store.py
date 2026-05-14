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
from nanobot.utils.helpers import _write_text_atomic

_LOCK = threading.Lock()
_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 8  # e.g. ABCD-EFGH
_TTL_DEFAULT_S = 600  # 10 minutes


def _store_path() -> Path:
    return get_data_dir() / "pairing.json"


def _load() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {"approved": {}, "pending": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupted pairing store, resetting")
        return {"approved": {}, "pending": {}}

    # Convert approved lists to sets for O(1) lookup
    for channel, users in data.get("approved", {}).items():
        data["approved"][channel] = set(users)
    return data


def _save(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Convert sets back to lists for JSON serialization
    payload = {
        "approved": {ch: sorted(list(users)) for ch, users in data.get("approved", {}).items()},
        "pending": dict(data.get("pending", {})),
    }
    _write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False))


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

    Returns the code (e.g. ``"ABCD-EFGH"``).
    """
    with _LOCK:
        data = _load()
        _gc_pending(data)
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
        code = f"{raw[:4]}-{raw[4:]}"

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
        data.setdefault("approved", {}).setdefault(channel, set()).add(sender_id)
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
        approved: dict[str, set[str]] = data.get("approved", {})
        return str(sender_id) in approved.get(channel, set())


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
        approved: dict[str, set[str]] = data.get("approved", {})
        users = approved.get(channel, set())
        if sender_id in users:
            users.discard(sender_id)
            if not users:
                del approved[channel]
            _save(data)
            logger.info("Revoked {} from {}", sender_id, channel)
            return True
        return False


def get_approved(channel: str) -> list[str]:
    """Return all approved sender IDs for *channel*."""
    with _LOCK:
        data = _load()
        return sorted(data.get("approved", {}).get(channel, set()))


def format_pairing_reply(code: str) -> str:
    """Return the pairing-code message sent to unrecognised DM senders."""
    return (
        "Hi there! This assistant only responds to approved users.\n\n"
        f"Your pairing code is: `{code}`\n\n"
        "To get access, ask the owner to approve this code:\n"
        f"- In this chat: send `/pairing approve {code}`\n"
        f"- Via CLI: run `nanobot pairing approve {code}`"
    )


def format_expiry(expires_at: float) -> str:
    """Return a human-readable expiry string (e.g. ``"120s"`` or ``"expired"``)."""
    remaining = int(expires_at - time.time())
    return f"{remaining}s" if remaining > 0 else "expired"


def handle_pairing_command(channel: str, subcommand_text: str) -> str:
    """Execute a pairing subcommand and return the reply text.

    This is a pure function (no side effects other than store mutations)
    so it can be used from both the CLI and the agent CommandRouter.
    """
    parts = subcommand_text.split()
    sub = parts[0] if parts else "list"
    arg = parts[1] if len(parts) > 1 else None

    if sub in ("list",):
        pending = list_pending()
        if not pending:
            return "No pending pairing requests."
        lines = ["Pending pairing requests:"]
        for item in pending:
            expiry = format_expiry(item.get("expires_at", 0))
            lines.append(
                f"- `{item['code']}` | {item['channel']} | {item['sender_id']} | {expiry}"
            )
        return "\n".join(lines)

    elif sub == "approve":
        if arg is None:
            return "Usage: `/pairing approve <code>`"
        result = approve_code(arg)
        if result is None:
            return f"Invalid or expired pairing code: `{arg}`"
        ch, sid = result
        return f"Approved pairing code `{arg}` — {sid} can now access {ch}"

    elif sub == "deny":
        if arg is None:
            return "Usage: `/pairing deny <code>`"
        if deny_code(arg):
            return f"Denied pairing code `{arg}`"
        return f"Pairing code `{arg}` not found or already expired"

    elif sub == "revoke":
        if arg is None:
            return "Usage: `/pairing revoke <user_id>` or `/pairing revoke <channel> <user_id>`"
        elif len(parts) == 2:
            return (
                f"Revoked {arg} from {channel}"
                if revoke(channel, arg)
                else f"{arg} was not in the approved list for {channel}"
            )
        elif len(parts) == 3:
            return (
                f"Revoked {parts[2]} from {arg}"
                if revoke(arg, parts[2])
                else f"{parts[2]} was not in the approved list for {arg}"
            )
        else:
            return "Usage: `/pairing revoke <user_id>` or `/pairing revoke <channel> <user_id>`"

    return (
        "Unknown pairing command.\n"
        "Usage: `/pairing [list|approve <code>|deny <code>|revoke <user_id>]`"
    )
