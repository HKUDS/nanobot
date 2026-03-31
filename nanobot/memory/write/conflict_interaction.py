"""User-facing conflict interaction helpers (extracted from conflicts.py).

Standalone functions that handle user prompts, reply parsing, relevance
gating, and conflict resolution dispatch.  Each function receives the
``ConflictManager`` instance (or nothing, for pure helpers) so that
``ConflictManager`` can delegate without duplicating logic.
"""

from __future__ import annotations

from typing import Any

from .._text import _norm_text, _tokenize, _utc_now_iso
from ..constants import CONFLICT_STATUS_NEEDS_USER
from ..persistence.conflict_types import ConflictRecord

__all__ = [
    "ask_user_for_conflict",
    "conflict_relevant_to",
    "get_next_user_conflict",
    "handle_user_conflict_reply",
    "parse_conflict_user_action",
]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def parse_conflict_user_action(text: str) -> str | None:
    """Parse a user reply into a conflict-resolution action code."""
    content = str(text or "").strip().lower()
    if not content:
        return None
    keep_old_markers = {"keep 1", "1", "old", "keep old", "keep_old"}
    keep_new_markers = {"keep 2", "2", "new", "keep new", "keep_new"}
    dismiss_markers = {"neither", "dismiss", "none", "skip"}
    merge_markers = {"merge", "combine"}
    if content in keep_old_markers:
        return "keep_old"
    if content in keep_new_markers:
        return "keep_new"
    if content in dismiss_markers:
        return "dismiss"
    if content in merge_markers:
        return "merge"
    return None


def conflict_relevant_to(conflict: ConflictRecord, user_message: str) -> bool:
    """Return True if the conflict topic overlaps with the user's message."""
    msg_tokens = _tokenize(_norm_text(user_message))
    if not msg_tokens:
        return True  # empty message -> don't filter
    old_tokens = _tokenize(_norm_text(conflict.old))
    new_tokens = _tokenize(_norm_text(conflict.new))
    conflict_tokens = old_tokens | new_tokens
    if not conflict_tokens:
        return True
    overlap = len(msg_tokens & conflict_tokens) / max(len(conflict_tokens), 1)
    return overlap >= 0.25


# ---------------------------------------------------------------------------
# Functions that need a ConflictManager instance
# ---------------------------------------------------------------------------


def get_next_user_conflict(mgr: Any) -> ConflictRecord | None:
    """Return the most-recently-asked conflict, or None.

    Only conflicts that have been explicitly presented to the user
    (``asked_at`` set) are eligible — this prevents ambiguous short
    replies like "1" from being silently hijacked as conflict resolutions
    when no conflict question was shown in the current conversation.
    """
    conflicts: list[ConflictRecord] = mgr.list_conflicts(include_closed=False)
    if not conflicts:
        return None

    asked = [c for c in conflicts if c.asked_at]
    if not asked:
        return None
    asked.sort(key=lambda c: c.asked_at)
    return asked[0]


def ask_user_for_conflict(
    mgr: Any,
    *,
    include_already_asked: bool = False,
    user_message: str = "",
) -> str | None:
    """Format and return a user-facing conflict prompt, or None."""
    profile = mgr.profile_mgr.read_profile()
    conflicts = profile.get("conflicts", [])
    if not isinstance(conflicts, list):
        return None

    chosen_idx: int | None = None
    chosen: ConflictRecord | None = None
    for idx, item in enumerate(conflicts):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "")).strip().lower()
        if status != CONFLICT_STATUS_NEEDS_USER:
            continue
        if not include_already_asked and item.get("asked_at"):
            continue
        record = ConflictRecord.from_dict(item, index=idx)
        # Relevance gate: if the user sent a message, only surface conflicts
        # whose topic overlaps with the message.  When there is no message
        # (e.g. interactive session start), skip the gate and show the first.
        if user_message and not conflict_relevant_to(record, user_message):
            continue
        chosen_idx = idx
        chosen = record
        break

    if chosen_idx is None or chosen is None:
        return None

    if not chosen.asked_at:
        # Write asked_at back to the raw profile dict.
        conflicts[chosen_idx]["asked_at"] = _utc_now_iso()
        mgr.profile_mgr.write_profile(profile)

    old_value = chosen.old.strip()
    new_value = chosen.new.strip()

    # Build richer provenance lines when timestamps are available.
    old_ts = chosen.old_last_seen_at.strip()
    new_ts = chosen.new_last_seen_at.strip()
    old_hint = f" (last seen: {old_ts[:10]})" if old_ts else ""
    new_hint = f" (last seen: {new_ts[:10]})" if new_ts else ""

    return (
        "I found a memory conflict and need your choice:\n"
        f"1. {old_value}{old_hint}\n"
        f"2. {new_value}{new_hint}\n"
        "Reply with: `keep 1`, `keep 2`, `merge`, or `neither`."
    )


def handle_user_conflict_reply(mgr: Any, text: str) -> dict[str, Any]:
    """Process a user's conflict-resolution reply and resolve the conflict."""
    action = parse_conflict_user_action(text)
    if action is None:
        return {"handled": False}

    conflict = get_next_user_conflict(mgr)
    if not conflict:
        return {"handled": False}

    idx = conflict.index
    if idx < 0:
        return {"handled": False}

    selected = "keep_new" if action == "merge" else action
    details = mgr.resolve_conflict_details(index=idx, action=selected)
    if not details.get("ok"):
        return {
            "handled": True,
            "ok": False,
            "message": "I couldn't resolve that conflict automatically. Please try `keep 1` or `keep 2`.",
        }

    return {
        "handled": True,
        "ok": True,
        "message": (
            f"Resolved conflict #{idx} with action `{selected}` "
            f"(db op: {details.get('db_operation', 'none')})."
        ),
    }
