"""Conflict resolution extracted from MemoryStore (LAN-203).

``ConflictManager`` owns the lifecycle of profile conflicts: listing,
auto-resolution, user-facing prompts, and final resolution with mem0
synchronisation.

All profile access is delegated to ``ProfileManager``; vector operations
go through ``_Mem0Adapter``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from .profile import ProfileManager

if TYPE_CHECKING:
    from .mem0_adapter import _Mem0Adapter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFLICT_STATUS_OPEN = "open"
CONFLICT_STATUS_NEEDS_USER = "needs_user"
CONFLICT_STATUS_RESOLVED = "resolved"

# ---------------------------------------------------------------------------
# ConflictManager
# ---------------------------------------------------------------------------


class ConflictManager:
    """Conflict listing, auto-resolution, user prompts, and resolution."""

    # Language patterns indicating a correction (new value supersedes old).
    _CORRECTION_MARKERS: ClassVar[tuple[str, ...]] = (
        "corrected",
        "changed to",
        "updated to",
        "actually",
        "replaced by",
        "switched to",
        "migrated to",
    )

    def __init__(
        self,
        profile_mgr: ProfileManager,
        mem0: _Mem0Adapter,
    ) -> None:
        self.profile_mgr = profile_mgr
        self.mem0 = mem0
        # Back-reference to the owning MemoryStore — set after construction.
        # Needed for _sanitize_mem0_text, _normalize_memory_metadata,
        # _sanitize_mem0_metadata which still live on MemoryStore.
        self._store: Any = None
        # Configurable auto-resolve confidence gap threshold — copied from
        # MemoryStore at wiring time.
        self.conflict_auto_resolve_gap: float = 0.25

    # -- helpers (delegated) ------------------------------------------------

    @staticmethod
    def _norm_text(value: str) -> str:
        import re

        return re.sub(r"\s+", " ", value.strip().lower())

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        import re

        return {t for t in re.findall(r"[a-zA-Z0-9_\-]+", value.lower()) if len(t) > 1}

    @staticmethod
    def _utc_now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    # -- public API ---------------------------------------------------------

    def list_conflicts(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        profile = self.profile_mgr.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return []

        out: list[dict[str, Any]] = []
        for idx, item in enumerate(conflicts):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", CONFLICT_STATUS_OPEN)).strip().lower()
            if not include_closed and status not in {
                CONFLICT_STATUS_OPEN,
                CONFLICT_STATUS_NEEDS_USER,
            }:
                continue
            row = dict(item)
            row["index"] = idx
            out.append(row)
        return out

    @staticmethod
    def _parse_conflict_user_action(text: str) -> str | None:
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

    def _auto_resolution_action(self, conflict: dict[str, Any]) -> str | None:
        source = str(conflict.get("source", "")).strip().lower()
        if source == "live_correction":
            # Live corrections surface conflicts for user review rather than
            # silently auto-resolving.  The user explicitly stated a change so
            # the conflict should be presented via ask_user_for_conflict().
            return None

        old_conf = self._safe_float(conflict.get("old_confidence"), 0.0)
        new_conf = self._safe_float(conflict.get("new_confidence"), 0.0)
        gap = abs(old_conf - new_conf)
        if gap >= self.conflict_auto_resolve_gap:
            return "keep_new" if new_conf > old_conf else "keep_old"

        # Temporal recency: when the confidence gap is too narrow, use
        # timestamps as a tiebreaker — newer facts supersede older ones.
        old_ts = str(conflict.get("old_last_seen_at", "")).strip()
        new_ts = str(conflict.get("new_last_seen_at", "")).strip()
        if old_ts and new_ts and old_ts != new_ts:
            return "keep_new" if new_ts > old_ts else "keep_old"

        # Correction language: if the *new* value contains correction markers,
        # treat it as an explicit supersession of the old value.
        new_text = self._norm_text(str(conflict.get("new", "")))
        if any(marker in new_text for marker in self._CORRECTION_MARKERS):
            return "keep_new"

        return None

    def auto_resolve_conflicts(self, *, max_items: int = 10) -> dict[str, int]:
        profile = self.profile_mgr.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return {"auto_resolved": 0, "needs_user": 0}

        auto_resolved = 0
        needs_user = 0
        touched = False
        for idx, conflict in enumerate(conflicts):
            if max_items <= 0:
                break
            if not isinstance(conflict, dict):
                continue
            status = str(conflict.get("status", CONFLICT_STATUS_OPEN)).strip().lower()
            if status not in {CONFLICT_STATUS_OPEN, CONFLICT_STATUS_NEEDS_USER}:
                continue
            max_items -= 1

            action = self._auto_resolution_action(conflict)
            if action is None:
                if status != CONFLICT_STATUS_NEEDS_USER:
                    conflict["status"] = CONFLICT_STATUS_NEEDS_USER
                    touched = True
                needs_user += 1
                continue

            details = self.resolve_conflict_details(idx, action)
            if details.get("ok"):
                auto_resolved += 1
                continue

            conflict["status"] = CONFLICT_STATUS_NEEDS_USER
            touched = True
            needs_user += 1

        if touched:
            self.profile_mgr.write_profile(profile)
        return {"auto_resolved": auto_resolved, "needs_user": needs_user}

    def get_next_user_conflict(self) -> dict[str, Any] | None:
        """Return the most-recently-asked conflict, or None.

        Only conflicts that have been explicitly presented to the user
        (``asked_at`` set) are eligible — this prevents ambiguous short
        replies like "1" from being silently hijacked as conflict resolutions
        when no conflict question was shown in the current conversation.
        """
        conflicts = self.list_conflicts(include_closed=False)
        if not conflicts:
            return None

        asked = [c for c in conflicts if isinstance(c.get("asked_at"), str) and c.get("asked_at")]
        if not asked:
            return None
        asked.sort(key=lambda c: str(c.get("asked_at", "")))
        return asked[0]

    def _conflict_relevant_to(self, conflict: dict[str, Any], user_message: str) -> bool:
        """Return True if the conflict topic overlaps with the user's message."""
        msg_tokens = self._tokenize(self._norm_text(user_message))
        if not msg_tokens:
            return True  # empty message → don't filter
        old_tokens = self._tokenize(self._norm_text(str(conflict.get("old", ""))))
        new_tokens = self._tokenize(self._norm_text(str(conflict.get("new", ""))))
        conflict_tokens = old_tokens | new_tokens
        if not conflict_tokens:
            return True
        overlap = len(msg_tokens & conflict_tokens) / max(len(conflict_tokens), 1)
        return overlap >= 0.25

    def ask_user_for_conflict(
        self,
        *,
        include_already_asked: bool = False,
        user_message: str = "",
    ) -> str | None:
        profile = self.profile_mgr.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return None

        chosen_idx: int | None = None
        chosen: dict[str, Any] | None = None
        for idx, item in enumerate(conflicts):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", CONFLICT_STATUS_OPEN)).strip().lower()
            if status != CONFLICT_STATUS_NEEDS_USER:
                continue
            if not include_already_asked and item.get("asked_at"):
                continue
            # Relevance gate: if the user sent a message, only surface conflicts
            # whose topic overlaps with the message.  When there is no message
            # (e.g. interactive session start), skip the gate and show the first.
            if user_message and not self._conflict_relevant_to(item, user_message):
                continue
            chosen_idx = idx
            chosen = item
            break

        if chosen_idx is None or chosen is None:
            return None

        if not chosen.get("asked_at"):
            chosen["asked_at"] = self._utc_now_iso()
            self.profile_mgr.write_profile(profile)

        old_value = str(chosen.get("old", "")).strip()
        new_value = str(chosen.get("new", "")).strip()

        # Build richer provenance lines when timestamps are available.
        old_ts = str(chosen.get("old_last_seen_at", "")).strip()
        new_ts = str(chosen.get("new_last_seen_at", "")).strip()
        old_hint = f" (last seen: {old_ts[:10]})" if old_ts else ""
        new_hint = f" (last seen: {new_ts[:10]})" if new_ts else ""

        return (
            "I found a memory conflict and need your choice:\n"
            f"1. {old_value}{old_hint}\n"
            f"2. {new_value}{new_hint}\n"
            "Reply with: `keep 1`, `keep 2`, `merge`, or `neither`."
        )

    def handle_user_conflict_reply(self, text: str) -> dict[str, Any]:
        action = self._parse_conflict_user_action(text)
        if action is None:
            return {"handled": False}

        conflict = self.get_next_user_conflict()
        if not conflict:
            return {"handled": False}

        idx = int(conflict.get("index", -1))
        if idx < 0:
            return {"handled": False}

        selected = "keep_new" if action == "merge" else action
        details = self.resolve_conflict_details(index=idx, action=selected)
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
                f"(mem0 op: {details.get('mem0_operation', 'none')})."
            ),
        }

    def resolve_conflict_details(self, index: int, action: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "index": index,
            "action": str(action or "").strip().lower(),
            "field": "",
            "old": "",
            "new": "",
            "old_memory_id": "",
            "new_memory_id": "",
            "mem0_operation": "none",
            "mem0_ok": False,
        }
        profile = self.profile_mgr.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list) or index < 0 or index >= len(conflicts):
            return result

        conflict = conflicts[index]
        if not isinstance(conflict, dict) or str(
            conflict.get("status", "")
        ).strip().lower() not in {
            CONFLICT_STATUS_OPEN,
            CONFLICT_STATUS_NEEDS_USER,
        }:
            return result

        field = str(conflict.get("field", ""))
        result["field"] = field
        try:
            key = self.profile_mgr._validate_profile_field(field)
        except ValueError:
            return result

        old_value = str(conflict.get("old", "")).strip()
        new_value = str(conflict.get("new", "")).strip()
        result["old"] = old_value
        result["new"] = new_value
        values = self.profile_mgr._to_str_list(profile.get(key))
        old_memory_id = str(
            conflict.get("old_memory_id", "")
        ).strip() or self.profile_mgr._find_mem0_id_for_text(old_value)
        new_memory_id = str(
            conflict.get("new_memory_id", "")
        ).strip() or self.profile_mgr._find_mem0_id_for_text(new_value)
        if old_memory_id:
            conflict["old_memory_id"] = old_memory_id
        if new_memory_id:
            conflict["new_memory_id"] = new_memory_id

        result["old_memory_id"] = old_memory_id
        result["new_memory_id"] = new_memory_id

        def _remove_value(values_in: list[str], target: str) -> list[str]:
            target_norm = self._norm_text(target)
            return [v for v in values_in if self._norm_text(v) != target_norm]

        store = self._store
        selected = str(action or "").strip().lower()
        mem0_ok = False

        # Look up belief IDs for the old and new values.
        old_entry = self.profile_mgr._meta_entry(profile, key, old_value)
        new_entry = self.profile_mgr._meta_entry(profile, key, new_value)
        old_belief_id = old_entry.get("id", "")
        new_belief_id = new_entry.get("id", "")

        if selected == "keep_old":
            if new_memory_id:
                mem0_ok = self.mem0.delete(new_memory_id)
                result["mem0_operation"] = "delete_new"
            else:
                mem0_ok = True
                result["mem0_operation"] = "none"
            values = _remove_value(values, new_value)
            # Boost winner confidence via update_belief.
            self.profile_mgr._update_belief_in_profile(
                profile,
                old_belief_id,
                confidence_delta=0.08,
                status=self.profile_mgr.PROFILE_STATUS_ACTIVE,
            )
            # Mark loser as stale.
            new_entry["status"] = self.profile_mgr.PROFILE_STATUS_STALE
            new_entry["last_seen_at"] = self._utc_now_iso()
            # Supersession chain (LAN-198).
            if old_belief_id and new_belief_id:
                new_entry["superseded_by_id"] = old_belief_id
                old_entry.setdefault("supersedes_id", new_belief_id)
        elif selected == "keep_new":
            clean_new_value = (
                store._sanitize_mem0_text(new_value, allow_archival=False) or new_value
            )
            if old_memory_id:
                mem0_ok = self.mem0.update(old_memory_id, clean_new_value)
                result["mem0_operation"] = "update_old_to_new"
                if mem0_ok and new_memory_id and new_memory_id != old_memory_id:
                    self.mem0.delete(new_memory_id)
                    conflict["new_memory_id"] = old_memory_id
                    result["new_memory_id"] = old_memory_id
            else:
                conflict_metadata, _ = store._normalize_memory_metadata(
                    {
                        "topic": "conflict_resolution",
                        "memory_type": "semantic",
                        "stability": "high",
                    },
                    event_type="fact",
                    summary=clean_new_value,
                    source="chat",
                )
                conflict_metadata.update({"event_type": "conflict_resolution", "field": key})
                conflict_metadata = store._sanitize_mem0_metadata(conflict_metadata)
                mem0_ok = (
                    self.mem0.add_text(
                        clean_new_value,
                        metadata=conflict_metadata,
                    )
                    if clean_new_value
                    else False
                )
                if mem0_ok:
                    result["mem0_operation"] = "add_new"
            values = _remove_value(values, old_value)
            # Boost winner confidence via update_belief.
            self.profile_mgr._update_belief_in_profile(
                profile,
                new_belief_id,
                confidence_delta=0.08,
                status=self.profile_mgr.PROFILE_STATUS_ACTIVE,
            )
            # Mark loser as stale.
            old_entry["status"] = self.profile_mgr.PROFILE_STATUS_STALE
            old_entry["last_seen_at"] = self._utc_now_iso()
            # Supersession chain (LAN-198).
            if new_belief_id and old_belief_id:
                old_entry["superseded_by_id"] = new_belief_id
                new_entry.setdefault("supersedes_id", old_belief_id)
        elif selected == "dismiss":
            mem0_ok = True
            result["mem0_operation"] = "none"
            self.profile_mgr._update_belief_in_profile(
                profile,
                old_belief_id,
                status=self.profile_mgr.PROFILE_STATUS_ACTIVE,
            )
            self.profile_mgr._update_belief_in_profile(
                profile,
                new_belief_id,
                status=self.profile_mgr.PROFILE_STATUS_ACTIVE,
            )
        else:
            return result

        result["mem0_ok"] = mem0_ok
        if not mem0_ok and self.mem0.enabled:
            return result

        profile[key] = values
        conflict["status"] = CONFLICT_STATUS_RESOLVED
        conflict["resolution"] = selected
        conflict["resolved_at"] = self._utc_now_iso()
        self.profile_mgr.write_profile(profile)
        result["ok"] = True
        return result

    def resolve_conflict(self, index: int, action: str) -> bool:
        return bool(self.resolve_conflict_details(index, action).get("ok"))
