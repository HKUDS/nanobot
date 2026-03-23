"""Profile/belief management extracted from MemoryStore (LAN-202).

``ProfileStore`` owns the profile CRUD lifecycle: reading/writing
``profile.json``, metadata bookkeeping, belief confidence tracking,
pin/stale management, contradiction detection, and live user corrections.

All file I/O is delegated to ``MemoryPersistence``; vector lookups go
through ``_Mem0Adapter``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from .event import BeliefRecord
from .helpers import _norm_text, _safe_float, _to_str_list, _tokenize, _utc_now_iso

if TYPE_CHECKING:
    from .mem0_adapter import _Mem0Adapter
    from .persistence import MemoryPersistence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROFILE_KEYS = (
    "preferences",
    "stable_facts",
    "active_projects",
    "relationships",
    "constraints",
)

PROFILE_STATUS_ACTIVE = "active"
PROFILE_STATUS_CONFLICTED = "conflicted"
PROFILE_STATUS_STALE = "stale"

__all__ = [
    "PROFILE_KEYS",
    "PROFILE_STATUS_ACTIVE",
    "PROFILE_STATUS_CONFLICTED",
    "PROFILE_STATUS_STALE",
    "ProfileCache",
    "ProfileStore",
]


# ---------------------------------------------------------------------------
# ProfileCache
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProfileCache:
    """Mtime-aware cache for profile.json. Owned exclusively by ProfileStore."""

    _path: Path
    _persistence: MemoryPersistence

    _data: dict[str, Any] | None = field(default=None, init=False)
    _mtime: float = field(default=-1.0, init=False)

    def read(self) -> dict[str, Any]:
        """Return cached data if file unchanged, else reload from disk."""
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            return {}
        if self._data is not None and mtime == self._mtime:
            return self._data
        self._data = self._persistence.read_json(self._path) or {}
        self._mtime = mtime
        return self._data

    def write(self, data: dict[str, Any]) -> None:
        """Write to disk and update cache atomically."""
        self._persistence.write_json(self._path, data)
        self._data = data
        try:
            self._mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._mtime = -1.0

    def invalidate(self) -> None:
        """Force next read() to reload from disk."""
        self._data = None
        self._mtime = -1.0


# ---------------------------------------------------------------------------
# ProfileStore
# ---------------------------------------------------------------------------


class ProfileStore:
    """Profile/belief CRUD, metadata bookkeeping, and live corrections."""

    # Duplicate constants as class attributes so call-sites using
    # ``self.PROFILE_KEYS`` etc. continue to work.
    PROFILE_KEYS = PROFILE_KEYS
    PROFILE_STATUS_ACTIVE = PROFILE_STATUS_ACTIVE
    PROFILE_STATUS_CONFLICTED = PROFILE_STATUS_CONFLICTED
    PROFILE_STATUS_STALE = PROFILE_STATUS_STALE
    _MAX_EVIDENCE_REFS = 10  # Cap evidence_event_ids to avoid unbounded growth.

    # Conflict status constants (referenced by _apply_profile_updates /
    # _has_open_conflict / apply_live_user_correction).
    CONFLICT_STATUS_OPEN = "open"
    CONFLICT_STATUS_NEEDS_USER = "needs_user"
    CONFLICT_STATUS_RESOLVED = "resolved"

    def __init__(
        self,
        persistence: MemoryPersistence,
        profile_file: Path,
        mem0: _Mem0Adapter,
        *,
        extractor: Any | None = None,
        ingester: Any | None = None,
        conflict_mgr: Any | None = None,
        snapshot: Any | None = None,
    ) -> None:
        self.persistence = persistence
        self.profile_file = profile_file
        self.mem0 = mem0
        # Subsystem references — set after construction by MemoryStore.__init__
        # (required by apply_live_user_correction).
        self._extractor: Any = extractor
        self._ingester: Any = ingester
        self._conflict_mgr: Any = conflict_mgr
        self._snapshot: Any = snapshot
        self._cache = ProfileCache(_path=profile_file, _persistence=persistence)
        self._corrector: Any = None  # wired post-construction by MemoryStore

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
        data = self._cache.read()
        if isinstance(data, dict) and data:
            # normalise legacy entries — same logic as before
            for key in self.PROFILE_KEYS:
                data.setdefault(key, [])
                if not isinstance(data[key], list):
                    data[key] = []
            data.setdefault("conflicts", [])
            data.setdefault("last_verified_at", None)
            data.setdefault("meta", {})
            for key in self.PROFILE_KEYS:
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
                            "status": self.PROFILE_STATUS_ACTIVE,
                            "created_at": fallback_ts,
                            "last_seen_at": fallback_ts,
                        }
                    elif not entry.get("id"):
                        created = entry.get("last_seen_at") or self._utc_now_iso()
                        entry.setdefault("created_at", created)
                        entry["id"] = self._generate_belief_id(key, norm, entry["created_at"])
            return data
        if self.profile_file.exists() and data is None:
            logger.warning("Failed to parse memory profile, resetting")
        return {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "last_verified_at": None,
            "meta": {key: {} for key in self.PROFILE_KEYS},
            "updated_at": self._utc_now_iso(),
        }

    def write_profile(self, profile: dict[str, Any]) -> None:
        profile["updated_at"] = self._utc_now_iso()
        self._cache.write(profile)

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
                "status": self.PROFILE_STATUS_ACTIVE,
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
        if key not in self.PROFILE_KEYS:
            raise ValueError(
                f"Invalid profile field '{field}'. Expected one of: {', '.join(self.PROFILE_KEYS)}"
            )
        return key

    # ------------------------------------------------------------------
    # Belief mutation API (LAN-205)
    # ------------------------------------------------------------------

    def _belief_from_meta(self, field: str, entry: dict[str, Any]) -> BeliefRecord:
        """Construct a BeliefRecord from a raw meta entry dict."""
        return BeliefRecord(
            id=entry.get("id", ""),
            field=field,
            text=entry.get("text", ""),
            confidence=self._safe_float(entry.get("confidence"), 0.65),
            evidence_count=int(entry.get("evidence_count", 1)),
            evidence_event_ids=list(entry.get("evidence_event_ids", [])),
            status=str(entry.get("status", PROFILE_STATUS_ACTIVE)),
            created_at=str(entry.get("created_at", "")),
            last_seen_at=str(entry.get("last_seen_at", "")),
            pinned=bool(entry.get("pinned", False)),
            supersedes_id=entry.get("supersedes_id"),
            superseded_by_id=entry.get("superseded_by_id"),
        )

    def _find_belief_by_id(
        self, profile: dict[str, Any], belief_id: str
    ) -> tuple[str, str, dict[str, Any]] | None:
        """Scan all profile meta sections for an entry with matching id.

        Returns ``(section_key, norm_text, entry_dict)`` or ``None``.
        """
        for section_key in self.PROFILE_KEYS:
            section = self._meta_section(profile, section_key)
            for norm_text, entry in section.items():
                if isinstance(entry, dict) and entry.get("id") == belief_id:
                    return section_key, norm_text, entry
        return None

    def get_belief_by_id(
        self, belief_id: str, *, profile: dict[str, Any] | None = None
    ) -> BeliefRecord | None:
        """Public accessor: look up a belief by its stable ID.

        If *profile* is ``None`` it will be read from disk.
        """
        if profile is None:
            profile = self.read_profile()
        result = self._find_belief_by_id(profile, belief_id)
        if result is None:
            return None
        section_key, _norm_text, entry = result
        return self._belief_from_meta(section_key, entry)

    def add_belief(
        self,
        field: str,
        text: str,
        *,
        confidence: float = 0.65,
        evidence_event_ids: list[str] | None = None,
        source: str = "consolidation",
    ) -> BeliefRecord:
        """Create a new belief, append it to the profile list, and return a BeliefRecord.

        This is the canonical way to add a new item to a profile section.
        It validates the field, creates the metadata entry, sets confidence
        and evidence links, and appends the text to ``profile[field]``.

        NOTE: this operates on a *fresh* profile read; callers that need to
        batch several mutations on a single profile dict should use the
        internal ``_add_belief_to_profile`` variant instead.
        """
        profile = self.read_profile()
        record = self._add_belief_to_profile(
            profile,
            field,
            text,
            confidence=confidence,
            evidence_event_ids=evidence_event_ids,
            source=source,
        )
        self.write_profile(profile)
        return record

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
        key = self._validate_profile_field(field)
        value = str(text or "").strip()
        if not value:
            raise ValueError("Belief text must not be empty")

        entry = self._meta_entry(profile, key, value)
        entry["confidence"] = min(max(confidence, 0.05), 0.99)
        now = self._utc_now_iso()
        entry.setdefault("created_at", now)
        entry["last_seen_at"] = now
        entry["status"] = PROFILE_STATUS_ACTIVE
        entry.setdefault("source", source)

        if evidence_event_ids:
            refs = entry.setdefault("evidence_event_ids", [])
            for eid in evidence_event_ids:
                if eid not in refs:
                    refs.append(eid)
            if len(refs) > self._MAX_EVIDENCE_REFS:
                del refs[: len(refs) - self._MAX_EVIDENCE_REFS]

        # Append to the profile list if not already present.
        values = self._to_str_list(profile.get(key))
        norm = self._norm_text(value)
        if norm not in {self._norm_text(v) for v in values}:
            values.append(value)
            profile[key] = values

        return self._belief_from_meta(key, entry)

    def update_belief(
        self,
        belief_id: str,
        *,
        confidence_delta: float = 0.0,
        new_evidence_ids: list[str] | None = None,
        new_text: str | None = None,
        status: str | None = None,
    ) -> BeliefRecord | None:
        """Update an existing belief by its stable ID.

        Returns the updated ``BeliefRecord``, or ``None`` if not found.
        """
        profile = self.read_profile()
        record = self._update_belief_in_profile(
            profile,
            belief_id,
            confidence_delta=confidence_delta,
            new_evidence_ids=new_evidence_ids,
            new_text=new_text,
            status=status,
        )
        if record is not None:
            self.write_profile(profile)
        return record

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
        result = self._find_belief_by_id(profile, belief_id)
        if result is None:
            return None

        section_key, old_norm, entry = result
        section = self._meta_section(profile, section_key)

        # If new_text is provided, update the text in the profile list and
        # re-key the meta dict entry.
        if new_text is not None:
            new_text = new_text.strip()
            if new_text:
                new_norm = self._norm_text(new_text)
                old_text = entry.get("text", "")

                # Update the profile list: replace old text with new.
                values = self._to_str_list(profile.get(section_key))
                old_norm_check = self._norm_text(old_text) if old_text else old_norm
                profile[section_key] = [
                    new_text if self._norm_text(v) == old_norm_check else v for v in values
                ]

                # Re-key in meta dict.
                if new_norm != old_norm:
                    del section[old_norm]
                    section[new_norm] = entry
                entry["text"] = new_text

        # Apply confidence/evidence/status deltas.
        evidence_id = new_evidence_ids[0] if new_evidence_ids else None
        self._touch_meta_entry(
            entry,
            confidence_delta=confidence_delta,
            status=status,
            evidence_event_id=evidence_id,
        )
        # Append any additional evidence IDs beyond the first (which
        # _touch_meta_entry already handled).
        if new_evidence_ids and len(new_evidence_ids) > 1:
            refs = entry.setdefault("evidence_event_ids", [])
            for eid in new_evidence_ids[1:]:
                if eid not in refs:
                    refs.append(eid)
            if len(refs) > self._MAX_EVIDENCE_REFS:
                del refs[: len(refs) - self._MAX_EVIDENCE_REFS]

        return self._belief_from_meta(section_key, entry)

    def retract_belief(
        self,
        belief_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
    ) -> bool:
        """Retract a belief by its stable ID.

        Sets the status to ``"stale"`` (or ``"retracted"``), optionally sets
        ``superseded_by_id``, and removes the text from the profile list.

        Returns ``True`` if the belief was found and retracted.
        """
        profile = self.read_profile()
        ok = self._retract_belief_in_profile(
            profile,
            belief_id,
            reason=reason,
            replacement_id=replacement_id,
        )
        if ok:
            self.write_profile(profile)
        return ok

    def _retract_belief_in_profile(
        self,
        profile: dict[str, Any],
        belief_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
    ) -> bool:
        """In-memory variant of ``retract_belief`` — mutates *profile* without writing."""
        result = self._find_belief_by_id(profile, belief_id)
        if result is None:
            return False

        section_key, _norm_text_key, entry = result

        entry["status"] = "retracted" if reason else PROFILE_STATUS_STALE
        entry["last_seen_at"] = self._utc_now_iso()
        if replacement_id:
            entry["superseded_by_id"] = replacement_id
        if reason:
            entry["retract_reason"] = reason

        # Remove from profile list.
        old_text = entry.get("text", "")
        if old_text:
            values = self._to_str_list(profile.get(section_key))
            old_norm = self._norm_text(old_text)
            profile[section_key] = [v for v in values if self._norm_text(v) != old_norm]

        return True

    # ------------------------------------------------------------------
    # Evidence-quality verification (LAN-209)
    # ------------------------------------------------------------------

    def verify_beliefs(self) -> dict[str, Any]:
        """Assess belief health based on evidence quality, not just timestamps.

        Returns a report with beliefs classified as healthy, weak, contradicted,
        or stale, plus a summary dict with counts.
        """
        profile = self.read_profile()
        report: dict[str, Any] = {
            "healthy": [],
            "weak": [],
            "contradicted": [],
            "stale": [],
        }

        for section_field in PROFILE_KEYS:
            for item in self._to_str_list(profile.get(section_field)):
                norm = self._norm_text(item)
                meta = profile.get("meta", {}).get(section_field, {}).get(norm, {})

                confidence = self._safe_float(meta.get("confidence"), 0.65)
                evidence_count = int(meta.get("evidence_count", 1))
                status = str(meta.get("status", PROFILE_STATUS_ACTIVE))
                superseded_by = meta.get("superseded_by_id")

                if superseded_by or status in ("stale", "retracted"):
                    report["stale"].append(
                        {
                            "field": section_field,
                            "text": item,
                            "reason": "superseded or retracted",
                        }
                    )
                elif status == PROFILE_STATUS_CONFLICTED:
                    report["contradicted"].append(
                        {
                            "field": section_field,
                            "text": item,
                            "reason": "has open conflict",
                        }
                    )
                elif confidence < 0.4 or evidence_count < 2:
                    report["weak"].append(
                        {
                            "field": section_field,
                            "text": item,
                            "reason": (
                                f"low evidence (count={evidence_count}, conf={confidence:.2f})"
                            ),
                        }
                    )
                else:
                    report["healthy"].append(
                        {
                            "field": section_field,
                            "text": item,
                            "confidence": confidence,
                        }
                    )

        report["summary"] = {
            "total": sum(len(v) for v in report.values() if isinstance(v, list)),
            "healthy": len(report["healthy"]),
            "weak": len(report["weak"]),
            "contradicted": len(report["contradicted"]),
            "stale": len(report["stale"]),
        }
        return report

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
        if entry.get("status") == self.PROFILE_STATUS_STALE and pinned:
            entry["status"] = self.PROFILE_STATUS_ACTIVE
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
        entry["status"] = self.PROFILE_STATUS_STALE
        entry["last_seen_at"] = self._utc_now_iso()
        self.write_profile(profile)
        return True

    def _conflict_pair(self, old_value: str, new_value: str) -> bool:
        """Delegate to ConflictManager._conflict_pair."""
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
        result: tuple[int, int, int] = self._conflict_mgr._apply_profile_updates(
            profile,
            updates,
            enable_contradiction_check=enable_contradiction_check,
            source_event_ids=source_event_ids,
        )
        return result

    def _has_open_conflict(
        self, profile: dict[str, Any], *, field: str, old_value: str, new_value: str
    ) -> bool:
        """Check for an open conflict matching the exact old/new value pair."""
        old_norm = self._norm_text(old_value)
        new_norm = self._norm_text(new_value)
        for item in profile.get("conflicts", []):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            if status not in {self.CONFLICT_STATUS_OPEN, self.CONFLICT_STATUS_NEEDS_USER}:
                continue
            if item.get("field") != field:
                continue
            if self._norm_text(str(item.get("old", ""))) != old_norm:
                continue
            if self._norm_text(str(item.get("new", ""))) != new_norm:
                continue
            return True
        return False

    # ------------------------------------------------------------------
    # mem0 helpers
    # ------------------------------------------------------------------

    def _find_mem0_id_for_text(self, text: str, *, top_k: int = 8) -> str | None:
        target = self._norm_text(text)
        if not target or not self.mem0.enabled:
            return None
        search_result = self.mem0.search(text, top_k=top_k)
        if isinstance(search_result, tuple) and len(search_result) == 2:
            rows = search_result[0]
        else:
            rows = search_result if isinstance(search_result, list) else []
        if not rows:
            return None

        for row in rows:
            summary = self._norm_text(str(row.get("summary", "")))
            if summary and (summary == target or target in summary or summary in target):
                value = str(row.get("id", "")).strip()
                if value:
                    return value
        value = str(rows[0].get("id", "")).strip()
        return value or None

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
        text = str(content or "").strip()
        if not text:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        preference_corrections = self._extractor.extract_explicit_preference_corrections(text)
        fact_corrections = self._extractor.extract_explicit_fact_corrections(text)
        if not preference_corrections and not fact_corrections:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        profile = self.read_profile()
        profile.setdefault("conflicts", [])
        applied = 0
        conflicts = 0
        events: list[dict[str, Any]] = []

        def _apply_field_corrections(
            *,
            field: str,
            event_type: str,
            correction_label: str,
            correction_pairs: list[tuple[str, str]],
        ) -> tuple[int, int]:
            local_applied = 0
            local_conflicts = 0
            values = self._to_str_list(profile.get(field))
            by_norm = {self._norm_text(v): v for v in values}

            for new_value, old_value in correction_pairs:
                old_norm = self._norm_text(old_value)
                new_norm = self._norm_text(new_value)
                if not new_norm:
                    continue

                # Add or touch the new belief via the mutation API.
                if new_norm not in by_norm:
                    self._add_belief_to_profile(
                        profile,
                        field,
                        new_value,
                        confidence=0.65,
                        source="live_correction",
                    )
                    # Sync local tracking structures after add.
                    values = self._to_str_list(profile.get(field))
                    by_norm[new_norm] = new_value
                    local_applied += 1

                new_entry = self._meta_entry(profile, field, by_norm[new_norm])
                self._touch_meta_entry(
                    new_entry, confidence_delta=0.08, status=self.PROFILE_STATUS_ACTIVE
                )

                if (
                    enable_contradiction_check
                    and old_norm in by_norm
                    and not self._has_open_conflict(
                        profile,
                        field=field,
                        old_value=by_norm[old_norm],
                        new_value=by_norm[new_norm],
                    )
                ):
                    old_entry = self._meta_entry(profile, field, by_norm[old_norm])
                    self._touch_meta_entry(
                        old_entry,
                        confidence_delta=-0.2,
                        min_confidence=0.35,
                        status=self.PROFILE_STATUS_CONFLICTED,
                    )
                    self._touch_meta_entry(
                        new_entry,
                        confidence_delta=-0.08,
                        min_confidence=0.35,
                        status=self.PROFILE_STATUS_CONFLICTED,
                    )
                    profile["conflicts"].append(
                        {
                            "timestamp": self._utc_now_iso(),
                            "field": field,
                            "old": by_norm[old_norm],
                            "new": by_norm[new_norm],
                            "old_memory_id": self._find_mem0_id_for_text(by_norm[old_norm]),
                            "new_memory_id": self._find_mem0_id_for_text(by_norm[new_norm]),
                            "status": self.CONFLICT_STATUS_OPEN,
                            "old_confidence": old_entry.get("confidence"),
                            "new_confidence": new_entry.get("confidence"),
                            "source": "live_correction",
                        }
                    )
                    local_conflicts += 1

                event = self._ingester._coerce_event(
                    {
                        "timestamp": self._utc_now_iso(),
                        "type": event_type,
                        "summary": (
                            f"User corrected {correction_label}: {new_value} (not {old_value})."
                        ),
                        "entities": [new_value, old_value],
                        "salience": 0.85,
                        "confidence": 0.9,
                        "ttl_days": 365,
                    },
                    source_span=[0, 0],
                    channel=channel,
                    chat_id=chat_id,
                )
                if event:
                    events.append(event)

            profile[field] = values
            return local_applied, local_conflicts

        pref_applied, pref_conflicts = _apply_field_corrections(
            field="preferences",
            event_type="preference",
            correction_label="preference",
            correction_pairs=preference_corrections,
        )
        fact_applied, fact_conflicts = _apply_field_corrections(
            field="stable_facts",
            event_type="fact",
            correction_label="fact",
            correction_pairs=fact_corrections,
        )
        applied += pref_applied + fact_applied
        conflicts += pref_conflicts + fact_conflicts

        if not applied and not conflicts:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        profile["last_verified_at"] = self._utc_now_iso()
        self.write_profile(profile)

        events_written = self._ingester.append_events(events)

        needs_user = 0
        question: str | None = None
        if conflicts > 0:
            resolution = self._conflict_mgr.auto_resolve_conflicts(max_items=10)
            needs_user = int(resolution.get("needs_user", 0))
            if needs_user > 0:
                question = self._conflict_mgr.ask_user_for_conflict()

        if self.mem0.enabled:
            correction_meta, _ = self._ingester._normalize_memory_metadata(
                {"topic": "user_correction", "memory_type": "episodic", "stability": "medium"},
                event_type="fact",
                summary=text,
                source="chat",
            )
            correction_meta.update(
                {
                    "event_type": "user_correction",
                    "timestamp": self._utc_now_iso(),
                    "channel": channel,
                    "chat_id": chat_id,
                }
            )
            correction_text = self._ingester._sanitize_mem0_text(text, allow_archival=False)
            correction_meta = self._ingester._sanitize_mem0_metadata(correction_meta)
            if correction_text:
                self.mem0.add_text(
                    correction_text,
                    metadata=correction_meta,
                )

        # Keep LLM-managed MEMORY.md content stable; snapshot can be generated on-demand.
        self._snapshot.rebuild_memory_snapshot(write=False)
        return {
            "applied": applied,
            "conflicts": conflicts,
            "events": events_written,
            "needs_user": needs_user,
            "question": question,
        }
