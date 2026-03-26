# size-exception: profile CRUD + belief lifecycle + metadata — single cohesive concern
"""Profile/belief management extracted from MemoryStore (LAN-202).

``ProfileStore`` owns the profile CRUD lifecycle: reading/writing
``profile.json``, metadata bookkeeping, belief confidence tracking,
pin/stale management, contradiction detection, and live user corrections.

All file I/O is delegated to ``MemoryPersistence``; vector lookups go
through ``UnifiedMemoryDB``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from .._text import _norm_text, _safe_float, _to_str_list, _tokenize, _utc_now_iso
from ..event import BeliefRecord

if TYPE_CHECKING:
    from ..unified_db import UnifiedMemoryDB

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
        *,
        db: UnifiedMemoryDB | None = None,
        conflict_mgr_fn: Callable[[], Any] | None = None,
        corrector_fn: Callable[[], Any] | None = None,
        extractor_fn: Callable[[], Any] | None = None,
        ingester_fn: Callable[[], Any] | None = None,
        snapshot_fn: Callable[[], Any] | None = None,
    ) -> None:
        self._db = db
        self._conflict_mgr_fn = conflict_mgr_fn
        self._corrector_fn = corrector_fn
        self._extractor_fn = extractor_fn
        self._ingester_fn = ingester_fn
        self._snapshot_fn = snapshot_fn
        self._cache = ProfileCache()

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
            "meta": {key: {} for key in self.PROFILE_KEYS},
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
        assert self._conflict_mgr_fn is not None, "_conflict_mgr_fn not wired"
        return bool(self._conflict_mgr_fn()._conflict_pair(old_value, new_value))

    def _apply_profile_updates(
        self,
        profile: dict[str, Any],
        updates: dict[str, list[str]],
        *,
        enable_contradiction_check: bool,
        source_event_ids: list[str] | None = None,
    ) -> tuple[int, int, int]:
        """Delegate to ConflictManager._apply_profile_updates."""
        assert self._conflict_mgr_fn is not None, "_conflict_mgr_fn not wired"
        result: tuple[int, int, int] = self._conflict_mgr_fn()._apply_profile_updates(
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

    def _has_open_conflict(self, profile: dict[str, Any], key: str) -> bool:
        """Delegating wrapper — see ConflictManager.has_open_conflict."""
        assert self._conflict_mgr_fn is not None, "_conflict_mgr_fn not wired"
        return bool(self._conflict_mgr_fn().has_open_conflict(profile, key))

    # ------------------------------------------------------------------
    # belief lookup helpers
    # ------------------------------------------------------------------

    def _find_belief_id_for_text(self, text: str, *, top_k: int = 8) -> str | None:
        target = self._norm_text(text)
        if not target:
            return None

        if self._db is not None:
            rows = self._db.search_fts(text, k=top_k)
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
        corrector = self._corrector_fn() if self._corrector_fn else None
        assert corrector is not None, "_corrector_fn not wired by MemoryStore"
        result: dict[str, Any] = corrector.apply_live_user_correction(
            content,
            channel=channel,
            chat_id=chat_id,
            enable_contradiction_check=enable_contradiction_check,
        )
        return result
