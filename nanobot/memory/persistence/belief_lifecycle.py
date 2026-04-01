"""Belief lifecycle functions extracted from ProfileStore (Task 4.1).

Standalone functions for belief CRUD (add/update/retract) and helpers
(belief_from_meta, find_belief_by_id, get_belief_by_id).  Each function
receives a ``ProfileStore`` instance as its first argument so it can
call ProfileStore helpers (_meta_section, _meta_entry, etc.).
"""

from __future__ import annotations

from typing import Any, Protocol

from .._text import _norm_text, _safe_float, _to_str_list, _utc_now_iso
from ..constants import (
    PROFILE_KEYS,
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_CONFLICTED,
    PROFILE_STATUS_STALE,
)
from ..event import BeliefRecord

__all__ = [
    "add_belief",
    "add_belief_to_profile",
    "belief_from_meta",
    "find_belief_by_id",
    "get_belief_by_id",
    "retract_belief",
    "retract_belief_in_profile",
    "update_belief",
    "update_belief_in_profile",
    "verify_beliefs",
]


class _ProfileStoreProtocol(Protocol):
    """Structural type for ProfileStore methods used by belief lifecycle functions."""

    _MAX_EVIDENCE_REFS: int

    def read_profile(self) -> dict[str, Any]: ...
    def write_profile(self, profile: dict[str, Any]) -> None: ...
    def _meta_section(self, profile: dict[str, Any], key: str) -> dict[str, Any]: ...
    def _meta_entry(self, profile: dict[str, Any], key: str, text: str) -> dict[str, Any]: ...
    def _touch_meta_entry(
        self,
        entry: dict[str, Any],
        *,
        confidence_delta: float,
        min_confidence: float = ...,
        max_confidence: float = ...,
        status: str | None = ...,
        evidence_event_id: str | None = ...,
    ) -> None: ...
    def _validate_profile_field(self, field: str) -> str: ...


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def belief_from_meta(field: str, entry: dict[str, Any]) -> BeliefRecord:
    """Construct a BeliefRecord from a raw meta entry dict."""
    return BeliefRecord(
        id=entry.get("id", ""),
        field=field,
        text=entry.get("text", ""),
        confidence=_safe_float(entry.get("confidence"), 0.65),
        evidence_count=int(entry.get("evidence_count", 1)),
        evidence_event_ids=list(entry.get("evidence_event_ids", [])),
        status=str(entry.get("status", PROFILE_STATUS_ACTIVE)),
        created_at=str(entry.get("created_at", "")),
        last_seen_at=str(entry.get("last_seen_at", "")),
        pinned=bool(entry.get("pinned", False)),
        supersedes_id=entry.get("supersedes_id"),
        superseded_by_id=entry.get("superseded_by_id"),
    )


def find_belief_by_id(
    store: _ProfileStoreProtocol,
    profile: dict[str, Any],
    belief_id: str,
) -> tuple[str, str, dict[str, Any]] | None:
    """Scan all profile meta sections for an entry with matching id.

    Returns ``(section_key, norm_text, entry_dict)`` or ``None``.
    """
    for section_key in PROFILE_KEYS:
        section = store._meta_section(profile, section_key)
        for norm_text_key, entry in section.items():
            if isinstance(entry, dict) and entry.get("id") == belief_id:
                return section_key, norm_text_key, entry
    return None


# ------------------------------------------------------------------
# Public read API
# ------------------------------------------------------------------


def get_belief_by_id(
    store: _ProfileStoreProtocol,
    belief_id: str,
    *,
    profile: dict[str, Any] | None = None,
) -> BeliefRecord | None:
    """Look up a belief by its stable ID.

    If *profile* is ``None`` it will be read from disk.
    """
    if profile is None:
        profile = store.read_profile()
    result = find_belief_by_id(store, profile, belief_id)
    if result is None:
        return None
    section_key, _norm, entry = result
    return belief_from_meta(section_key, entry)


# ------------------------------------------------------------------
# Add
# ------------------------------------------------------------------


def add_belief(
    store: _ProfileStoreProtocol,
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
    batch several mutations on a single profile dict should use
    ``add_belief_to_profile`` instead.
    """
    profile = store.read_profile()
    record = add_belief_to_profile(
        store,
        profile,
        field,
        text,
        confidence=confidence,
        evidence_event_ids=evidence_event_ids,
        source=source,
    )
    store.write_profile(profile)
    return record


def add_belief_to_profile(
    store: _ProfileStoreProtocol,
    profile: dict[str, Any],
    field: str,
    text: str,
    *,
    confidence: float = 0.65,
    evidence_event_ids: list[str] | None = None,
    source: str = "consolidation",
) -> BeliefRecord:
    """In-memory variant of ``add_belief`` -- mutates *profile* without writing."""
    key = store._validate_profile_field(field)
    value = str(text or "").strip()
    if not value:
        raise ValueError("Belief text must not be empty")

    entry = store._meta_entry(profile, key, value)
    entry["confidence"] = min(max(confidence, 0.05), 0.99)
    now = _utc_now_iso()
    entry.setdefault("created_at", now)
    entry["last_seen_at"] = now
    entry["status"] = PROFILE_STATUS_ACTIVE
    entry.setdefault("source", source)

    if evidence_event_ids:
        refs = entry.setdefault("evidence_event_ids", [])
        for eid in evidence_event_ids:
            if eid not in refs:
                refs.append(eid)
        if len(refs) > store._MAX_EVIDENCE_REFS:
            del refs[: len(refs) - store._MAX_EVIDENCE_REFS]

    # Append to the profile list if not already present.
    values = _to_str_list(profile.get(key))
    norm = _norm_text(value)
    if norm not in {_norm_text(v) for v in values}:
        values.append(value)
        profile[key] = values

    return belief_from_meta(key, entry)


# ------------------------------------------------------------------
# Update
# ------------------------------------------------------------------


def update_belief(
    store: _ProfileStoreProtocol,
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
    profile = store.read_profile()
    record = update_belief_in_profile(
        store,
        profile,
        belief_id,
        confidence_delta=confidence_delta,
        new_evidence_ids=new_evidence_ids,
        new_text=new_text,
        status=status,
    )
    if record is not None:
        store.write_profile(profile)
    return record


def update_belief_in_profile(
    store: _ProfileStoreProtocol,
    profile: dict[str, Any],
    belief_id: str,
    *,
    confidence_delta: float = 0.0,
    new_evidence_ids: list[str] | None = None,
    new_text: str | None = None,
    status: str | None = None,
) -> BeliefRecord | None:
    """In-memory variant of ``update_belief`` -- mutates *profile* without writing."""
    result = find_belief_by_id(store, profile, belief_id)
    if result is None:
        return None

    section_key, old_norm, entry = result
    section = store._meta_section(profile, section_key)

    # If new_text is provided, update the text in the profile list and
    # re-key the meta dict entry.
    if new_text is not None:
        new_text = new_text.strip()
        if new_text:
            new_norm = _norm_text(new_text)
            old_text = entry.get("text", "")

            # Update the profile list: replace old text with new.
            values = _to_str_list(profile.get(section_key))
            old_norm_check = _norm_text(old_text) if old_text else old_norm
            profile[section_key] = [
                new_text if _norm_text(v) == old_norm_check else v for v in values
            ]

            # Re-key in meta dict.
            if new_norm != old_norm:
                del section[old_norm]
                section[new_norm] = entry
            entry["text"] = new_text

    # Apply confidence/evidence/status deltas.
    evidence_id = new_evidence_ids[0] if new_evidence_ids else None
    store._touch_meta_entry(
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
        if len(refs) > store._MAX_EVIDENCE_REFS:
            del refs[: len(refs) - store._MAX_EVIDENCE_REFS]

    return belief_from_meta(section_key, entry)


# ------------------------------------------------------------------
# Retract
# ------------------------------------------------------------------


def retract_belief(
    store: _ProfileStoreProtocol,
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
    profile = store.read_profile()
    ok = retract_belief_in_profile(
        store,
        profile,
        belief_id,
        reason=reason,
        replacement_id=replacement_id,
    )
    if ok:
        store.write_profile(profile)
    return ok


def retract_belief_in_profile(
    store: _ProfileStoreProtocol,
    profile: dict[str, Any],
    belief_id: str,
    *,
    reason: str = "",
    replacement_id: str | None = None,
) -> bool:
    """In-memory variant of ``retract_belief`` -- mutates *profile* without writing."""
    result = find_belief_by_id(store, profile, belief_id)
    if result is None:
        return False

    section_key, _norm_text_key, entry = result

    entry["status"] = "retracted" if reason else PROFILE_STATUS_STALE
    entry["last_seen_at"] = _utc_now_iso()
    if replacement_id:
        entry["superseded_by_id"] = replacement_id
    if reason:
        entry["retract_reason"] = reason

    # Remove from profile list.
    old_text = entry.get("text", "")
    if old_text:
        values = _to_str_list(profile.get(section_key))
        old_norm = _norm_text(old_text)
        profile[section_key] = [v for v in values if _norm_text(v) != old_norm]

    return True


# ------------------------------------------------------------------
# Verification
# ------------------------------------------------------------------


def verify_beliefs(store: _ProfileStoreProtocol) -> dict[str, Any]:
    """Assess belief health based on evidence quality.

    Returns a report with beliefs classified as healthy, weak, contradicted,
    or stale, plus a summary dict with counts.
    """
    profile = store.read_profile()
    report: dict[str, Any] = {
        "healthy": [],
        "weak": [],
        "contradicted": [],
        "stale": [],
    }

    for section_field in PROFILE_KEYS:
        for item in _to_str_list(profile.get(section_field)):
            norm = _norm_text(item)
            meta = profile.get("meta", {}).get(section_field, {}).get(norm, {})

            confidence = _safe_float(meta.get("confidence"), 0.65)
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
                        "reason": (f"low evidence (count={evidence_count}, conf={confidence:.2f})"),
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
