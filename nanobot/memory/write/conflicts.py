# size-exception: single-class module with resolution logic that shares state across methods
"""Conflict resolution extracted from MemoryStore (LAN-203).

``ConflictManager`` owns the lifecycle of profile conflicts: listing,
auto-resolution, user-facing prompts, and final resolution with database
synchronisation.

All profile access is delegated to ``ProfileManager``; vector operations
go through ``MemoryDatabase``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from .._text import _norm_text, _safe_float, _tokenize, _utc_now_iso
from ..constants import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    CONFLICT_STATUS_RESOLVED,
    PROFILE_KEYS,
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_CONFLICTED,
    PROFILE_STATUS_STALE,
)
from ..persistence.profile_io import ProfileStore as ProfileManager

if TYPE_CHECKING:
    from nanobot.config.memory import MemoryConfig

    from ..db.connection import MemoryDatabase
    from ..persistence.profile_io import ProfileStore

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
        profile_store: ProfileStore | ProfileManager,
        *,
        db: MemoryDatabase | None = None,
        memory_config: MemoryConfig | None = None,
    ) -> None:
        # Stored as profile_mgr for backward compat with resolve_conflict_details callers.
        self.profile_mgr = profile_store
        self._db = db
        self._memory_config = memory_config

    # -- Shared helpers imported from .helpers --------------------------------
    _norm_text = staticmethod(_norm_text)
    _safe_float = staticmethod(_safe_float)
    _tokenize = staticmethod(_tokenize)
    _utc_now_iso = staticmethod(_utc_now_iso)

    # -- Methods moved from ProfileStore (LAN-Task2) -----------------------

    def _conflict_pair(self, old_value: str, new_value: str) -> bool:
        """Return True if old_value and new_value represent a genuine conflict.

        A conflict is detected when one value contains a negation marker and
        the other does not, and the two values share sufficient token overlap.
        """
        old_n = self._norm_text(old_value)
        new_n = self._norm_text(new_value)
        if not old_n or not new_n or old_n == new_n:
            return False
        old_has_not = " not " in f" {old_n} " or "n't" in old_n
        new_has_not = " not " in f" {new_n} " or "n't" in new_n
        if old_has_not == new_has_not:
            return False
        old_tokens = self._tokenize(old_n.replace("not", ""))
        new_tokens = self._tokenize(new_n.replace("not", ""))
        if not old_tokens or not new_tokens:
            return False
        overlap = len(old_tokens & new_tokens) / max(len(old_tokens | new_tokens), 1)
        return overlap >= 0.55

    def _apply_profile_updates(
        self,
        profile: dict[str, Any],
        updates: dict[str, list[str]],
        *,
        enable_contradiction_check: bool,
        source_event_ids: list[str] | None = None,
    ) -> tuple[int, int, int]:
        """Apply profile field updates, detecting contradictions.

        Returns (added, conflicts, touched) counts.
        """
        added = 0
        conflicts = 0
        touched = 0
        profile.setdefault("conflicts", [])
        evidence_ids = [source_event_ids[0]] if source_event_ids else None

        for key in PROFILE_KEYS:
            values = self.profile_mgr._to_str_list(profile.get(key))
            seen = {self.profile_mgr._norm_text(v) for v in values}
            for candidate in self.profile_mgr._to_str_list(updates.get(key)):
                normalized = self.profile_mgr._norm_text(candidate)
                if not normalized:
                    continue

                if normalized in seen:
                    # Existing belief — bump confidence.
                    entry = self.profile_mgr._meta_entry(profile, key, candidate)
                    belief_id = entry.get("id", "")
                    if belief_id:
                        self.profile_mgr._update_belief_in_profile(
                            profile,
                            belief_id,
                            confidence_delta=0.03,
                            new_evidence_ids=evidence_ids,
                            status=PROFILE_STATUS_ACTIVE,
                        )
                    else:
                        self.profile_mgr._touch_meta_entry(
                            entry,
                            confidence_delta=0.03,
                            status=PROFILE_STATUS_ACTIVE,
                            evidence_event_id=evidence_ids[0] if evidence_ids else None,
                        )
                    touched += 1
                    continue

                # Check for contradictions against the existing values
                # (before appending the candidate).
                existing_values_snapshot = list(values)

                # Use _add_belief_to_profile to create the entry and append
                # to the profile list.
                self.profile_mgr._add_belief_to_profile(
                    profile,
                    key,
                    candidate,
                    confidence=0.65,
                    evidence_event_ids=evidence_ids,
                    source="consolidation",
                )
                # Reconcile: _add_belief_to_profile appends to profile[key],
                # keep local values/seen in sync.
                values = self.profile_mgr._to_str_list(profile.get(key))
                seen.add(normalized)

                has_conflict = False
                if enable_contradiction_check:
                    for existing in existing_values_snapshot:
                        if self._conflict_pair(existing, candidate):
                            has_conflict = True
                            old_entry = self.profile_mgr._meta_entry(profile, key, existing)
                            self.profile_mgr._touch_meta_entry(
                                old_entry,
                                confidence_delta=-0.12,
                                status=PROFILE_STATUS_CONFLICTED,
                            )
                            new_entry = self.profile_mgr._meta_entry(profile, key, candidate)
                            self.profile_mgr._touch_meta_entry(
                                new_entry,
                                confidence_delta=-0.2,
                                min_confidence=0.35,
                                status=PROFILE_STATUS_CONFLICTED,
                                evidence_event_id=evidence_ids[0] if evidence_ids else None,
                            )
                            # Include belief IDs in conflict record (LAN-198).
                            profile["conflicts"].append(
                                {
                                    "timestamp": self._utc_now_iso(),
                                    "field": key,
                                    "old": existing,
                                    "new": candidate,
                                    "old_memory_id": self.profile_mgr._find_belief_id_for_text(
                                        existing
                                    ),
                                    "new_memory_id": self.profile_mgr._find_belief_id_for_text(
                                        candidate
                                    ),
                                    "belief_id_old": old_entry.get("id", ""),
                                    "belief_id_new": new_entry.get("id", ""),
                                    "status": CONFLICT_STATUS_OPEN,
                                    "old_confidence": old_entry.get("confidence"),
                                    "new_confidence": new_entry.get("confidence"),
                                    "old_last_seen_at": old_entry.get("last_seen_at", ""),
                                    "new_last_seen_at": new_entry.get("last_seen_at", ""),
                                }
                            )
                            conflicts += 1
                            touched += 2
                            break

                if not has_conflict:
                    # Boost confidence for non-conflicted new beliefs.
                    entry = self.profile_mgr._meta_entry(profile, key, candidate)
                    self.profile_mgr._touch_meta_entry(
                        entry,
                        confidence_delta=0.1,
                        status=PROFILE_STATUS_ACTIVE,
                        evidence_event_id=evidence_ids[0] if evidence_ids else None,
                    )
                    touched += 1
                added += 1

            profile[key] = values

        return added, conflicts, touched

    def has_open_conflict(self, profile: dict[str, Any], key: str) -> bool:
        """Return True if any open conflict exists for the given profile key."""
        for c in profile.get("conflicts", []):
            if not isinstance(c, dict):
                continue
            if str(c.get("field", "")) != key:
                continue
            status = str(c.get("status", "")).lower()
            if status in {"open", "needs_user"}:
                return True
        return False

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
        from .conflict_interaction import parse_conflict_user_action

        return parse_conflict_user_action(text)

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
        resolve_gap = self._memory_config.conflict_auto_resolve_gap if self._memory_config else 0.25
        if gap >= resolve_gap:
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
        """Return the most-recently-asked conflict, or None."""
        from .conflict_interaction import get_next_user_conflict

        return get_next_user_conflict(self)

    def _conflict_relevant_to(self, conflict: dict[str, Any], user_message: str) -> bool:
        """Return True if the conflict topic overlaps with the user's message."""
        from .conflict_interaction import conflict_relevant_to

        return conflict_relevant_to(conflict, user_message)

    def ask_user_for_conflict(
        self,
        *,
        include_already_asked: bool = False,
        user_message: str = "",
    ) -> str | None:
        from .conflict_interaction import ask_user_for_conflict

        return ask_user_for_conflict(
            self,
            include_already_asked=include_already_asked,
            user_message=user_message,
        )

    def handle_user_conflict_reply(self, text: str) -> dict[str, Any]:
        from .conflict_interaction import handle_user_conflict_reply

        return handle_user_conflict_reply(self, text)

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
            "db_operation": "none",
            "db_ok": False,
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
        ).strip() or self.profile_mgr._find_belief_id_for_text(old_value)
        new_memory_id = str(
            conflict.get("new_memory_id", "")
        ).strip() or self.profile_mgr._find_belief_id_for_text(new_value)
        if old_memory_id:
            conflict["old_memory_id"] = old_memory_id
        if new_memory_id:
            conflict["new_memory_id"] = new_memory_id

        result["old_memory_id"] = old_memory_id
        result["new_memory_id"] = new_memory_id

        def _remove_value(values_in: list[str], target: str) -> list[str]:
            target_norm = self._norm_text(target)
            return [v for v in values_in if self._norm_text(v) != target_norm]

        selected = str(action or "").strip().lower()
        db_ok = False

        # Look up belief IDs for the old and new values.
        old_entry = self.profile_mgr._meta_entry(profile, key, old_value)
        new_entry = self.profile_mgr._meta_entry(profile, key, new_value)
        old_belief_id = old_entry.get("id", "")
        new_belief_id = new_entry.get("id", "")

        if selected == "keep_old":
            db_ok = True
            result["db_operation"] = "none_db"
            values = _remove_value(values, new_value)
            # Boost winner confidence via update_belief.
            self.profile_mgr._update_belief_in_profile(
                profile,
                old_belief_id,
                confidence_delta=0.08,
                status=PROFILE_STATUS_ACTIVE,
            )
            # Mark loser as stale.
            new_entry["status"] = PROFILE_STATUS_STALE
            new_entry["last_seen_at"] = self._utc_now_iso()
            # Supersession chain (LAN-198).
            if old_belief_id and new_belief_id:
                new_entry["superseded_by_id"] = old_belief_id
                old_entry.setdefault("supersedes_id", new_belief_id)
        elif selected == "keep_new":
            db_ok = True
            result["db_operation"] = "none_db"
            values = _remove_value(values, old_value)
            # Boost winner confidence via update_belief.
            self.profile_mgr._update_belief_in_profile(
                profile,
                new_belief_id,
                confidence_delta=0.08,
                status=PROFILE_STATUS_ACTIVE,
            )
            # Mark loser as stale.
            old_entry["status"] = PROFILE_STATUS_STALE
            old_entry["last_seen_at"] = self._utc_now_iso()
            # Supersession chain (LAN-198).
            if new_belief_id and old_belief_id:
                old_entry["superseded_by_id"] = new_belief_id
                new_entry.setdefault("supersedes_id", old_belief_id)
        elif selected == "dismiss":
            db_ok = True
            result["db_operation"] = "none"
            self.profile_mgr._update_belief_in_profile(
                profile,
                old_belief_id,
                status=PROFILE_STATUS_ACTIVE,
            )
            self.profile_mgr._update_belief_in_profile(
                profile,
                new_belief_id,
                status=PROFILE_STATUS_ACTIVE,
            )
        else:
            return result

        result["db_ok"] = db_ok
        if not db_ok:
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
