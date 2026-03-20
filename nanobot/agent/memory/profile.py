"""Profile/belief management extracted from MemoryStore (LAN-202).

``ProfileManager`` owns the profile CRUD lifecycle: reading/writing
``profile.json``, metadata bookkeeping, belief confidence tracking,
pin/stale management, contradiction detection, and live user corrections.

All file I/O is delegated to ``MemoryPersistence``; vector lookups go
through ``_Mem0Adapter``.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from .event import BeliefRecord

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

_MAX_EVIDENCE_REFS = 10  # Cap evidence_event_ids to avoid unbounded growth.


# ---------------------------------------------------------------------------
# ProfileManager
# ---------------------------------------------------------------------------


class ProfileManager:
    """Profile/belief CRUD, metadata bookkeeping, and live corrections."""

    # Duplicate constants as class attributes so call-sites using
    # ``self.PROFILE_KEYS`` etc. continue to work.
    PROFILE_KEYS = PROFILE_KEYS
    PROFILE_STATUS_ACTIVE = PROFILE_STATUS_ACTIVE
    PROFILE_STATUS_CONFLICTED = PROFILE_STATUS_CONFLICTED
    PROFILE_STATUS_STALE = PROFILE_STATUS_STALE
    _MAX_EVIDENCE_REFS = _MAX_EVIDENCE_REFS

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
    ) -> None:
        self.persistence = persistence
        self.profile_file = profile_file
        self.mem0 = mem0
        # Back-reference to the owning MemoryStore — set by MemoryStore.__init__
        # after construction.  Required by apply_live_user_correction which calls
        # store-level orchestration methods (append_events, auto_resolve_conflicts,
        # etc.).
        self._store: Any = None

    # ------------------------------------------------------------------
    # Static helpers (duplicated from MemoryStore so ProfileManager is
    # self-contained; the originals remain on MemoryStore for other callers)
    # ------------------------------------------------------------------

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _norm_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        return {t for t in re.findall(r"[a-zA-Z0-9_\-]+", value.lower()) if len(t) > 1}

    @staticmethod
    def _to_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    @staticmethod
    def _generate_belief_id(section: str, norm_text: str, created_at: str) -> str:
        """Generate a deterministic stable ID for a profile item."""
        raw = f"{section}|{norm_text}|{created_at}"
        return "bf-" + hashlib.sha1(raw.encode()).hexdigest()[:8]

    # ------------------------------------------------------------------
    # Core profile CRUD
    # ------------------------------------------------------------------

    def read_profile(self) -> dict[str, Any]:
        data = self.persistence.read_json(self.profile_file)
        if isinstance(data, dict):
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
                        # Backfill stable ID on legacy entries.
                        created = entry.get("last_seen_at") or self._utc_now_iso()
                        entry.setdefault("created_at", created)
                        entry["id"] = self._generate_belief_id(key, norm, entry["created_at"])
            return data
        if self.profile_file.exists():
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
        self.persistence.write_json(self.profile_file, profile)

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
        added = 0
        conflicts = 0
        touched = 0
        profile.setdefault("conflicts", [])
        # Use the first source event ID as evidence link for all updates in this
        # batch.  More granular per-item linking requires changes to the extractor
        # output format (future work).
        evidence_ids = [source_event_ids[0]] if source_event_ids else None

        for key in self.PROFILE_KEYS:
            values = self._to_str_list(profile.get(key))
            seen = {self._norm_text(v) for v in values}
            for candidate in self._to_str_list(updates.get(key)):
                normalized = self._norm_text(candidate)
                if not normalized:
                    continue

                if normalized in seen:
                    # Existing belief — bump confidence.
                    entry = self._meta_entry(profile, key, candidate)
                    belief_id = entry.get("id", "")
                    if belief_id:
                        self._update_belief_in_profile(
                            profile,
                            belief_id,
                            confidence_delta=0.03,
                            new_evidence_ids=evidence_ids,
                            status=self.PROFILE_STATUS_ACTIVE,
                        )
                    else:
                        self._touch_meta_entry(
                            entry,
                            confidence_delta=0.03,
                            status=self.PROFILE_STATUS_ACTIVE,
                            evidence_event_id=evidence_ids[0] if evidence_ids else None,
                        )
                    touched += 1
                    continue

                # Check for contradictions against the existing values
                # (before appending the candidate).
                existing_values_snapshot = list(values)

                # Use _add_belief_to_profile to create the entry and append
                # to the profile list.
                self._add_belief_to_profile(
                    profile,
                    key,
                    candidate,
                    confidence=0.65,
                    evidence_event_ids=evidence_ids,
                    source="consolidation",
                )
                # Reconcile: _add_belief_to_profile appends to profile[key],
                # keep local values/seen in sync.
                values = self._to_str_list(profile.get(key))
                seen.add(normalized)

                has_conflict = False
                if enable_contradiction_check:
                    for existing in existing_values_snapshot:
                        if self._conflict_pair(existing, candidate):
                            has_conflict = True
                            old_entry = self._meta_entry(profile, key, existing)
                            self._touch_meta_entry(
                                old_entry,
                                confidence_delta=-0.12,
                                status=self.PROFILE_STATUS_CONFLICTED,
                            )
                            new_entry = self._meta_entry(profile, key, candidate)
                            self._touch_meta_entry(
                                new_entry,
                                confidence_delta=-0.2,
                                min_confidence=0.35,
                                status=self.PROFILE_STATUS_CONFLICTED,
                                evidence_event_id=evidence_ids[0] if evidence_ids else None,
                            )
                            # Include belief IDs in conflict record (LAN-198).
                            profile["conflicts"].append(
                                {
                                    "timestamp": self._utc_now_iso(),
                                    "field": key,
                                    "old": existing,
                                    "new": candidate,
                                    "old_memory_id": self._find_mem0_id_for_text(existing),
                                    "new_memory_id": self._find_mem0_id_for_text(candidate),
                                    "belief_id_old": old_entry.get("id", ""),
                                    "belief_id_new": new_entry.get("id", ""),
                                    "status": self.CONFLICT_STATUS_OPEN,
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
                    entry = self._meta_entry(profile, key, candidate)
                    self._touch_meta_entry(
                        entry,
                        confidence_delta=0.1,
                        status=self.PROFILE_STATUS_ACTIVE,
                        evidence_event_id=evidence_ids[0] if evidence_ids else None,
                    )
                    touched += 1
                added += 1

            profile[key] = values

        return added, conflicts, touched

    def _has_open_conflict(
        self, profile: dict[str, Any], *, field: str, old_value: str, new_value: str
    ) -> bool:
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

        # _store is the owning MemoryStore — needed for extractor access and
        # store-level orchestration (append_events, auto_resolve_conflicts, etc.).
        store = self._store

        preference_corrections = store.extractor.extract_explicit_preference_corrections(text)
        fact_corrections = store.extractor.extract_explicit_fact_corrections(text)
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

                event = store._coerce_event(
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

        events_written = store.append_events(events)

        needs_user = 0
        question: str | None = None
        if conflicts > 0:
            resolution = store.auto_resolve_conflicts(max_items=10)
            needs_user = int(resolution.get("needs_user", 0))
            if needs_user > 0:
                question = store.ask_user_for_conflict()

        if self.mem0.enabled:
            correction_meta, _ = store._normalize_memory_metadata(
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
            correction_text = store._sanitize_mem0_text(text, allow_archival=False)
            correction_meta = store._sanitize_mem0_metadata(correction_meta)
            if correction_text:
                self.mem0.add_text(
                    correction_text,
                    metadata=correction_meta,
                )

        # Keep LLM-managed MEMORY.md content stable; snapshot can be generated on-demand.
        store.rebuild_memory_snapshot(write=False)
        return {
            "applied": applied,
            "conflicts": conflicts,
            "events": events_written,
            "needs_user": needs_user,
            "question": question,
        }
