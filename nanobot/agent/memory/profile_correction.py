"""CorrectionOrchestrator: live user correction pipeline.

Extracted from ProfileStore. Receives all dependencies via constructor
injection — no back-references to MemoryStore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .conflicts import ConflictManager
    from .extractor import MemoryExtractor
    from .ingester import EventIngester
    from .profile_io import ProfileStore
    from .snapshot import MemorySnapshot


__all__ = ["CorrectionOrchestrator"]


class CorrectionOrchestrator:
    """Owns the apply_live_user_correction pipeline."""

    def __init__(
        self,
        *,
        profile_store: ProfileStore,
        extractor: MemoryExtractor,
        ingester: EventIngester,
        conflict_mgr: ConflictManager,
        snapshot: MemorySnapshot,
    ) -> None:
        self._profile_store = profile_store
        self._extractor = extractor
        self._ingester = ingester
        self._conflict_mgr = conflict_mgr
        self._snapshot = snapshot

    def apply_live_user_correction(
        self,
        content: str,
        *,
        channel: str = "",
        chat_id: str = "",
        enable_contradiction_check: bool = True,
    ) -> dict[str, Any]:
        """Apply live user correction to the profile."""
        text = str(content or "").strip()
        if not text:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        preference_corrections = self._extractor.extract_explicit_preference_corrections(text)
        fact_corrections = self._extractor.extract_explicit_fact_corrections(text)
        if not preference_corrections and not fact_corrections:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        profile = self._profile_store.read_profile()
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
            values = self._profile_store._to_str_list(profile.get(field))
            by_norm = {self._profile_store._norm_text(v): v for v in values}

            for new_value, old_value in correction_pairs:
                old_norm = self._profile_store._norm_text(old_value)
                new_norm = self._profile_store._norm_text(new_value)
                if not new_norm:
                    continue

                # Add or touch the new belief via the mutation API.
                if new_norm not in by_norm:
                    self._profile_store._add_belief_to_profile(
                        profile,
                        field,
                        new_value,
                        confidence=0.65,
                        source="live_correction",
                    )
                    # Sync local tracking structures after add.
                    values = self._profile_store._to_str_list(profile.get(field))
                    by_norm[new_norm] = new_value
                    local_applied += 1

                new_entry = self._profile_store._meta_entry(profile, field, by_norm[new_norm])
                self._profile_store._touch_meta_entry(
                    new_entry,
                    confidence_delta=0.08,
                    status=self._profile_store.PROFILE_STATUS_ACTIVE,
                )

                if (
                    enable_contradiction_check
                    and old_norm in by_norm
                    and not self._profile_store._has_exact_conflict_pair(
                        profile,
                        field=field,
                        old_value=by_norm[old_norm],
                        new_value=by_norm[new_norm],
                    )
                ):
                    old_entry = self._profile_store._meta_entry(profile, field, by_norm[old_norm])
                    self._profile_store._touch_meta_entry(
                        old_entry,
                        confidence_delta=-0.2,
                        min_confidence=0.35,
                        status=self._profile_store.PROFILE_STATUS_CONFLICTED,
                    )
                    self._profile_store._touch_meta_entry(
                        new_entry,
                        confidence_delta=-0.08,
                        min_confidence=0.35,
                        status=self._profile_store.PROFILE_STATUS_CONFLICTED,
                    )
                    profile["conflicts"].append(
                        {
                            "timestamp": self._profile_store._utc_now_iso(),
                            "field": field,
                            "old": by_norm[old_norm],
                            "new": by_norm[new_norm],
                            "old_memory_id": self._profile_store._find_mem0_id_for_text(
                                by_norm[old_norm]
                            ),
                            "new_memory_id": self._profile_store._find_mem0_id_for_text(
                                by_norm[new_norm]
                            ),
                            "status": self._profile_store.CONFLICT_STATUS_OPEN,
                            "old_confidence": old_entry.get("confidence"),
                            "new_confidence": new_entry.get("confidence"),
                            "source": "live_correction",
                        }
                    )
                    local_conflicts += 1

                event = self._ingester._coerce_event(
                    {
                        "timestamp": self._profile_store._utc_now_iso(),
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

        profile["last_verified_at"] = self._profile_store._utc_now_iso()
        self._profile_store.write_profile(profile)

        events_written = self._ingester.append_events(events)

        needs_user = 0
        question: str | None = None
        if conflicts > 0:
            resolution = self._conflict_mgr.auto_resolve_conflicts(max_items=10)
            needs_user = int(resolution.get("needs_user", 0))
            if needs_user > 0:
                question = self._conflict_mgr.ask_user_for_conflict()

        if self._profile_store.mem0.enabled:
            correction_meta, _ = self._ingester._normalize_memory_metadata(
                {"topic": "user_correction", "memory_type": "episodic", "stability": "medium"},
                event_type="fact",
                summary=text,
                source="chat",
            )
            correction_meta.update(
                {
                    "event_type": "user_correction",
                    "timestamp": self._profile_store._utc_now_iso(),
                    "channel": channel,
                    "chat_id": chat_id,
                }
            )
            correction_text = self._ingester._sanitize_mem0_text(text, allow_archival=False)
            correction_meta = self._ingester._sanitize_mem0_metadata(correction_meta)
            if correction_text:
                self._profile_store.mem0.add_text(
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
