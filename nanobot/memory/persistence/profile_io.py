"""Profile/belief management extracted from MemoryStore (LAN-202).

``ProfileStore`` owns the profile CRUD lifecycle: reading/writing
``profile.json``, metadata bookkeeping, belief confidence tracking,
pin/stale management, contradiction detection, and live user corrections.

Belief mutation methods (add/update/retract + helpers) are implemented in
``belief_lifecycle.py`` and delegated from thin stubs here to preserve API
compatibility.

All file I/O is delegated to ``MemoryPersistence``; vector lookups go
through ``MemoryDatabase``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from .._text import _norm_text, _safe_float, _to_str_list, _tokenize, _utc_now_iso
from ..constants import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    PROFILE_KEYS,
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_STALE,
)
from ..event import BeliefRecord
from .belief_lifecycle import (
    add_belief as _add_belief,
)
from .belief_lifecycle import (
    add_belief_to_profile as _add_belief_to_profile,
)
from .belief_lifecycle import (
    belief_from_meta as _belief_from_meta,
)
from .belief_lifecycle import (
    find_belief_by_id as _find_belief_by_id,
)
from .belief_lifecycle import (
    get_belief_by_id as _get_belief_by_id,
)
from .belief_lifecycle import (
    retract_belief as _retract_belief,
)
from .belief_lifecycle import (
    retract_belief_in_profile as _retract_belief_in_profile,
)
from .belief_lifecycle import (
    update_belief as _update_belief,
)
from .belief_lifecycle import (
    update_belief_in_profile as _update_belief_in_profile,
)
from .belief_lifecycle import (
    verify_beliefs as _verify_beliefs,
)

if TYPE_CHECKING:
    from ..db.connection import MemoryDatabase

__all__ = [
    "ProfileCache",
    "ProfileStore",
]


# ---------------------------------------------------------------------------
# ProfileCache
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProfileCache:
    """Simple in-memory profile cache. Owned exclusively by ProfileStore."""

    _data: dict[str, Any] | None = field(default=None, init=False)

    def read(self) -> dict[str, Any]:
        """Return cached data (or empty dict if not yet written)."""
        return self._data if self._data is not None else {}

    def write(self, data: dict[str, Any]) -> None:
        """Update cache."""
        self._data = data

    def invalidate(self) -> None:
        """Force next read() to return empty."""
        self._data = None


# ---------------------------------------------------------------------------
# ProfileStore
# ---------------------------------------------------------------------------


class ProfileStore:
    """Profile/belief CRUD, metadata bookkeeping, and live corrections."""

    _MAX_EVIDENCE_REFS = 10  # Cap evidence_event_ids to avoid unbounded growth.

    def __init__(
        self,
        *,
        db: MemoryDatabase | None = None,
    ) -> None:
        self._db = db
        self._conflict_mgr: Any | None = None  # set via set_conflict_mgr() after construction
        self._corrector: Any | None = None  # set via set_corrector() after construction
        self._cache = ProfileCache()

    def set_conflict_mgr(self, conflict_mgr: Any) -> None:
        """Post-construction wiring: set conflict manager (breaks circular dep)."""
        self._conflict_mgr = conflict_mgr

    def set_corrector(self, corrector: Any) -> None:
        """Post-construction wiring: set correction orchestrator (breaks circular dep)."""
        self._corrector = corrector

    # -- Shared helpers imported from .helpers --------------------------------
    _utc_now_iso = staticmethod(_utc_now_iso)
    _safe_float = staticmethod(_safe_float)
    _norm_text = staticmethod(_norm_text)
    _tokenize = staticmethod(_tokenize)
    _to_str_list = staticmethod(_to_str_list)

    @staticmethod
    def _generate_belief_id(section: str, norm_text: str, created_at: str) -> str:
        """Generate a deterministic stable ID for a profile item."""
        raw = f"{section}|{norm_text}|{created_at}"
        return "bf-" + hashlib.sha1(raw.encode()).hexdigest()[:8]

    # ------------------------------------------------------------------
    # Core profile CRUD
    # ------------------------------------------------------------------

    def read_profile(self) -> dict[str, Any]:
        if self._db is not None:
            data = self._db.read_profile("profile")
        else:
            data = self._cache.read() or {}
        if isinstance(data, dict) and data:
            # normalise legacy entries — same logic as before
            for key in PROFILE_KEYS:
                data.setdefault(key, [])
                if not isinstance(data[key], list):
                    data[key] = []
            data.setdefault("conflicts", [])
            data.setdefault("last_verified_at", None)
            data.setdefault("meta", {})
            for key in PROFILE_KEYS:
                section_meta = data["meta"].get(key)
                if not isinstance(section_meta, dict):
                    section_meta = {}
                    data["meta"][key] = section_meta
                for item in data[key]:
                    if not isinstance(item, str) or not item.strip():
                        continue
                    norm = self._norm_text(item)
                    entry = section_meta.get(norm)
                    if not isinstance(entry, dict):
                        fallback_ts = data.get("updated_at") or self._utc_now_iso()
                        section_meta[norm] = {
                            "id": self._generate_belief_id(key, norm, fallback_ts),
                            "text": item,
                            "confidence": 0.65,
                            "evidence_count": 1,
                            "status": PROFILE_STATUS_ACTIVE,
                            "created_at": fallback_ts,
                            "last_seen_at": fallback_ts,
                        }
                    elif not entry.get("id"):
                        created = entry.get("last_seen_at") or self._utc_now_iso()
                        entry.setdefault("created_at", created)
                        entry["id"] = self._generate_belief_id(key, norm, entry["created_at"])
            return data
        if data is None:
            logger.warning("Failed to parse memory profile, resetting")
        return {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "last_verified_at": None,
            "meta": {key: {} for key in PROFILE_KEYS},
            "updated_at": self._utc_now_iso(),
        }

    def write_profile(self, profile: dict[str, Any]) -> None:
        profile["updated_at"] = self._utc_now_iso()
        if self._db is not None:
            self._db.write_profile("profile", profile)
        else:
            self._cache.write(profile)  # in-memory fallback

    def _meta_section(self, profile: dict[str, Any], key: str) -> dict[str, Any]:
        profile.setdefault("meta", {})
        section = profile["meta"].get(key)
        if not isinstance(section, dict):
            section = {}
            profile["meta"][key] = section
        return section

    def _meta_entry(self, profile: dict[str, Any], key: str, text: str) -> dict[str, Any]:
        norm = self._norm_text(text)
        section = self._meta_section(profile, key)
        entry = section.get(norm)
        if not isinstance(entry, dict):
            now = self._utc_now_iso()
            entry = {
                "id": self._generate_belief_id(key, norm, now),
                "text": text,
                "confidence": 0.65,
                "evidence_count": 1,
                "status": PROFILE_STATUS_ACTIVE,
                "created_at": now,
                "last_seen_at": now,
            }
            section[norm] = entry
        elif not entry.get("id"):
            # Backfill stable ID on legacy entries (migration-on-read).
            created = entry.get("last_seen_at") or self._utc_now_iso()
            entry.setdefault("created_at", created)
            entry["id"] = self._generate_belief_id(key, norm, entry["created_at"])
        return entry

    def _touch_meta_entry(
        self,
        entry: dict[str, Any],
        *,
        confidence_delta: float,
        min_confidence: float = 0.05,
        max_confidence: float = 0.99,
        status: str | None = None,
        evidence_event_id: str | None = None,
    ) -> None:
        current_conf = self._safe_float(entry.get("confidence"), 0.65)
        entry["confidence"] = min(
            max(current_conf + confidence_delta, min_confidence), max_confidence
        )
        evidence = int(entry.get("evidence_count", 0)) + 1
        entry["evidence_count"] = max(evidence, 1)
        entry["last_seen_at"] = self._utc_now_iso()
        if status:
            entry["status"] = status
        # Append evidence link (LAN-197).
        if evidence_event_id:
            refs = entry.setdefault("evidence_event_ids", [])
            if evidence_event_id not in refs:
                refs.append(evidence_event_id)
                if len(refs) > self._MAX_EVIDENCE_REFS:
                    del refs[: len(refs) - self._MAX_EVIDENCE_REFS]

    def _validate_profile_field(self, field: str) -> str:
        key = str(field or "").strip()
        if key not in PROFILE_KEYS:
            raise ValueError(
                f"Invalid profile field '{field}'. Expected one of: {', '.join(PROFILE_KEYS)}"
            )
        return key

    # ------------------------------------------------------------------
    # Belief mutation API (LAN-205)
    # ------------------------------------------------------------------

    def _belief_from_meta(self, field: str, entry: dict[str, Any]) -> BeliefRecord:
        """Construct a BeliefRecord from a raw meta entry dict."""
        return _belief_from_meta(field, entry)

    def _find_belief_by_id(
        self, profile: dict[str, Any], belief_id: str
    ) -> tuple[str, str, dict[str, Any]] | None:
        """Scan all profile meta sections for an entry with matching id."""
        return _find_belief_by_id(self, profile, belief_id)

    def get_belief_by_id(
        self, belief_id: str, *, profile: dict[str, Any] | None = None
    ) -> BeliefRecord | None:
        """Public accessor: look up a belief by its stable ID."""
        return _get_belief_by_id(self, belief_id, profile=profile)

    def add_belief(
        self,
        field: str,
        text: str,
        *,
        confidence: float = 0.65,
        evidence_event_ids: list[str] | None = None,
        source: str = "consolidation",
    ) -> BeliefRecord:
        """Create a new belief, append it to the profile list, and return a BeliefRecord."""
        return _add_belief(
            self,
            field,
            text,
            confidence=confidence,
            evidence_event_ids=evidence_event_ids,
            source=source,
        )

    def _add_belief_to_profile(
        self,
        profile: dict[str, Any],
        field: str,
        text: str,
        *,
        confidence: float = 0.65,
        evidence_event_ids: list[str] | None = None,
        source: str = "consolidation",
    ) -> BeliefRecord:
        """In-memory variant of ``add_belief`` — mutates *profile* without writing."""
        return _add_belief_to_profile(
            self,
            profile,
            field,
            text,
            confidence=confidence,
            evidence_event_ids=evidence_event_ids,
            source=source,
        )

    def update_belief(
        self,
        belief_id: str,
        *,
        confidence_delta: float = 0.0,
        new_evidence_ids: list[str] | None = None,
        new_text: str | None = None,
        status: str | None = None,
    ) -> BeliefRecord | None:
        """Update an existing belief by its stable ID."""
        return _update_belief(
            self,
            belief_id,
            confidence_delta=confidence_delta,
            new_evidence_ids=new_evidence_ids,
            new_text=new_text,
            status=status,
        )

    def _update_belief_in_profile(
        self,
        profile: dict[str, Any],
        belief_id: str,
        *,
        confidence_delta: float = 0.0,
        new_evidence_ids: list[str] | None = None,
        new_text: str | None = None,
        status: str | None = None,
    ) -> BeliefRecord | None:
        """In-memory variant of ``update_belief`` — mutates *profile* without writing."""
        return _update_belief_in_profile(
            self,
            profile,
            belief_id,
            confidence_delta=confidence_delta,
            new_evidence_ids=new_evidence_ids,
            new_text=new_text,
            status=status,
        )

    def retract_belief(
        self,
        belief_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
    ) -> bool:
        """Retract a belief by its stable ID."""
        return _retract_belief(self, belief_id, reason=reason, replacement_id=replacement_id)

    def _retract_belief_in_profile(
        self,
        profile: dict[str, Any],
        belief_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
    ) -> bool:
        """In-memory variant of ``retract_belief`` — mutates *profile* without writing."""
        return _retract_belief_in_profile(
            self, profile, belief_id, reason=reason, replacement_id=replacement_id
        )

    # ------------------------------------------------------------------
    # Evidence-quality verification (LAN-209)
    # ------------------------------------------------------------------

    def verify_beliefs(self) -> dict[str, Any]:
        """Assess belief health based on evidence quality."""
        return _verify_beliefs(self)

    # ------------------------------------------------------------------
    # Profile mutation (legacy helpers)
    # ------------------------------------------------------------------

    def set_item_pin(self, field: str, text: str, *, pinned: bool) -> bool:
        key = self._validate_profile_field(field)
        value = str(text or "").strip()
        if not value:
            return False

        profile = self.read_profile()
        values = self._to_str_list(profile.get(key))
        normalized = self._norm_text(value)
        existing_map = {self._norm_text(v): v for v in values}
        if normalized not in existing_map:
            values.append(value)
            profile[key] = values

        canonical = existing_map.get(normalized, value)
        entry = self._meta_entry(profile, key, canonical)
        entry["pinned"] = bool(pinned)
        entry["last_seen_at"] = self._utc_now_iso()
        if entry.get("status") == PROFILE_STATUS_STALE and pinned:
            entry["status"] = PROFILE_STATUS_ACTIVE
        self.write_profile(profile)
        return True

    def mark_item_outdated(self, field: str, text: str) -> bool:
        key = self._validate_profile_field(field)
        value = str(text or "").strip()
        if not value:
            return False

        profile = self.read_profile()
        values = self._to_str_list(profile.get(key))
        normalized = self._norm_text(value)
        existing = None
        for item in values:
            if self._norm_text(item) == normalized:
                existing = item
                break

        if existing is None:
            return False

        entry = self._meta_entry(profile, key, existing)
        entry["status"] = PROFILE_STATUS_STALE
        entry["last_seen_at"] = self._utc_now_iso()
        self.write_profile(profile)
        return True

    def _conflict_pair(self, old_value: str, new_value: str) -> bool:
        """Delegate to ConflictManager._conflict_pair."""
        assert self._conflict_mgr is not None, "conflict_mgr not wired — call set_conflict_mgr()"
        return bool(self._conflict_mgr._conflict_pair(old_value, new_value))

    def _apply_profile_updates(
        self,
        profile: dict[str, Any],
        updates: dict[str, list[str]],
        *,
        enable_contradiction_check: bool,
        source_event_ids: list[str] | None = None,
    ) -> tuple[int, int, int]:
        """Delegate to ConflictManager._apply_profile_updates."""
        assert self._conflict_mgr is not None, "conflict_mgr not wired — call set_conflict_mgr()"
        result: tuple[int, int, int] = self._conflict_mgr._apply_profile_updates(
            profile,
            updates,
            enable_contradiction_check=enable_contradiction_check,
            source_event_ids=source_event_ids,
        )
        return result

    def _has_exact_conflict_pair(
        self, profile: dict[str, Any], *, field: str, old_value: str, new_value: str
    ) -> bool:
        """Check for an open conflict matching the exact old/new value pair."""
        old_norm = self._norm_text(old_value)
        new_norm = self._norm_text(new_value)
        for item in profile.get("conflicts", []):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", CONFLICT_STATUS_OPEN)).strip().lower()
            if status not in {CONFLICT_STATUS_OPEN, CONFLICT_STATUS_NEEDS_USER}:
                continue
            if item.get("field") != field:
                continue
            if self._norm_text(str(item.get("old", ""))) != old_norm:
                continue
            if self._norm_text(str(item.get("new", ""))) != new_norm:
                continue
            return True
        return False

    def _has_open_conflict(self, profile: dict[str, Any], key: str) -> bool:
        """Delegating wrapper — see ConflictManager.has_open_conflict."""
        assert self._conflict_mgr is not None, "conflict_mgr not wired — call set_conflict_mgr()"
        return bool(self._conflict_mgr.has_open_conflict(profile, key))

    # ------------------------------------------------------------------
    # belief lookup helpers
    # ------------------------------------------------------------------

    def _find_belief_id_for_text(self, text: str, *, top_k: int = 8) -> str | None:
        target = self._norm_text(text)
        if not target:
            return None

        if self._db is not None:
            rows = self._db.event_store.search_fts(text, k=top_k)
            if rows:
                value = str(rows[0].get("id", "")).strip()
                return value or None
        return None

    # ------------------------------------------------------------------
    # Live correction
    # ------------------------------------------------------------------

    def apply_live_user_correction(
        self,
        content: str,
        *,
        channel: str = "",
        chat_id: str = "",
        enable_contradiction_check: bool = True,
    ) -> dict[str, Any]:
        """Facade — delegates to CorrectionOrchestrator wired by MemoryStore."""
        assert self._corrector is not None, "corrector not wired — call set_corrector()"
        result: dict[str, Any] = self._corrector.apply_live_user_correction(
            content,
            channel=channel,
            chat_id=chat_id,
            enable_contradiction_check=enable_contradiction_check,
        )
        return result
