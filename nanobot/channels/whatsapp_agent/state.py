"""Durable poll cursor and dedup state for the WhatsApp Agent Platform channel.

The Agent Platform long-poll contract has three properties that force an
explicit, crash-safe store on the channel side:

* ``next_offset`` must be stored as a 64-bit signed integer and replayed
  unchanged; the server never accepts a client-computed cursor.
* Polling does not consume updates, so a re-read replays the same messages
  until the retention window (30 days) expires.
* Marking a message read may delete it server-side, so a message must be
  recorded before its receipt is acknowledged.

The store keeps the cursor, the recently handled wamids, and accumulated
contact display names in one atomically replaced JSON file.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from nanobot.utils.helpers import atomic_write_lines

# Dedup window. One creator talks to the agent, so a few hundred ids cover any
# realistic replay after a reconnect or a failed batch.
_SEEN_MAX = 2000


def token_fingerprint(token: str) -> str:
    """Return an opaque, non-reversible identifier for a token value."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""


def local_state_present(section: Any) -> bool:
    """Return whether the channel already has a durable poll cursor on disk."""
    from nanobot.channels.contracts import channel_field_value

    configured_dir = channel_field_value(section, "stateDir")
    state_dir = (
        Path(str(configured_dir)).expanduser()
        if configured_dir
        else default_state_dir()
    )
    try:
        decoded = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    payload = _json_object(decoded)
    if payload is None:
        return False
    return bool(str(payload.get("token_fingerprint") or "").strip())


def default_state_dir() -> Path:
    """Return the default runtime directory owned by this channel."""
    from nanobot.config.paths import get_runtime_subdir

    return get_runtime_subdir("whatsapp-agent")


@dataclass
class WhatsAppAgentState:
    """Crash-safe cursor, dedup window, and contact-name cache."""

    offset: int | None = None
    initialized: bool = False
    token_fingerprint: str = ""
    # Most recent inbound identifier, kept so a restart can reply before the
    # next message arrives. The API only accepts this value in ``to``.
    creator_id: str = ""
    # Ordered oldest-first so trimming drops the least recently seen wamid.
    seen: OrderedDict[str, None] = field(default_factory=OrderedDict)
    last_status: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> WhatsAppAgentState:
        """Load persisted state, returning a fresh store when unreadable."""
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cls()
        payload = _json_object(decoded)
        if payload is None:
            return cls()

        raw_seen = payload.get("seen")
        seen_items = cast(list[object], raw_seen) if isinstance(raw_seen, list) else []
        seen_entries = [
            str(item) for item in seen_items if isinstance(item, str | int)
        ]
        statuses = _string_map(payload.get("last_status"))
        return cls(
            offset=_optional_int(payload.get("offset")),
            initialized=bool(payload.get("initialized")),
            token_fingerprint=str(payload.get("token_fingerprint") or ""),
            creator_id=str(payload.get("creator_id") or ""),
            seen=OrderedDict.fromkeys(seen_entries[-_SEEN_MAX:]),
            last_status=statuses,
        )

    def save(self, path: Path) -> None:
        """Atomically replace the persisted snapshot."""
        payload = {
            "offset": self.offset,
            "initialized": self.initialized,
            "token_fingerprint": self.token_fingerprint,
            "creator_id": self.creator_id,
            "seen": list(self.seen),
            "last_status": self.last_status,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        # fsync keeps the cursor durable across a crash: a lost cursor means a
        # replayed batch, and a cursor written before the batch is committed
        # would drop messages.
        atomic_write_lines(path, [json.dumps(payload, ensure_ascii=False)])

    def reset_for_token(self, token: str) -> bool:
        """Discard cursor state when the configured token identifies a new agent.

        ``next_offset`` is only meaningful for the agent that issued it, so a
        rotated or replaced token starts a fresh stream. Returns True when the
        caller must re-resolve the head on the next poll.
        """
        fingerprint = token_fingerprint(token)
        if fingerprint and fingerprint == self.token_fingerprint:
            return False
        self.offset = None
        self.initialized = False
        self.creator_id = ""
        self.seen.clear()
        self.last_status.clear()
        self.token_fingerprint = fingerprint
        return True

    def note_creator(self, sender: str) -> None:
        """Remember the creator identifier from the freshest inbound message."""
        if sender:
            self.creator_id = sender

    def accept_offset(self, next_offset: int) -> None:
        """Store the server cursor exactly as issued."""
        self.offset = next_offset
        self.initialized = True

    def note_message(self, wamid: str) -> None:
        """Record a handled wamid so a replayed batch does not repeat it."""
        if not wamid:
            return
        self.seen[wamid] = None
        self.seen.move_to_end(wamid)
        while len(self.seen) > _SEEN_MAX:
            self.seen.popitem(last=False)

    def has_message(self, wamid: str) -> bool:
        return bool(wamid) and wamid in self.seen

    def note_status(self, wamid: str, status: str) -> None:
        """Remember the latest delivery receipt for an outbound message."""
        if not wamid or not status:
            return
        self.last_status[wamid] = status
        while len(self.last_status) > _SEEN_MAX:
            self.last_status.pop(next(iter(self.last_status)))


def _json_object(value: object) -> dict[str, Any] | None:
    """Narrow decoded JSON to a string-keyed object."""
    if not isinstance(value, dict):
        return None
    return cast(dict[str, Any], value)


def _string_map(value: object) -> dict[str, str]:
    """Narrow a persisted JSON value to a flat string map."""
    if not isinstance(value, dict):
        return {}
    mapping = cast(dict[object, object], value)
    return {
        str(key): str(item)
        for key, item in mapping.items()
        if item is not None and not isinstance(item, bool)
    }


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


__all__ = [
    "WhatsAppAgentState",
    "default_state_dir",
    "local_state_present",
    "token_fingerprint",
]
