"""Tests for the belief state layer: stable IDs, pinned sections, evidence linking."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.memory import MemoryStore
from nanobot.agent.memory.snapshot import MemorySnapshot

# ---------------------------------------------------------------------------
# LAN-196: Stable IDs for profile item metadata
# ---------------------------------------------------------------------------


class TestStableBeliefIds:
    def test_new_meta_entry_has_id_and_created_at(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        entry = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Python")

        assert "id" in entry
        assert entry["id"].startswith("bf-")
        assert len(entry["id"]) == 11  # "bf-" + 8 hex chars
        assert "created_at" in entry
        assert entry["created_at"]  # non-empty

    def test_stable_id_is_deterministic(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        entry = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Python")
        first_id = entry["id"]

        # Re-reading the same entry returns the same ID.
        entry2 = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Python")
        assert entry2["id"] == first_id

    def test_different_items_get_different_ids(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        e1 = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Python")
        e2 = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Rust")
        assert e1["id"] != e2["id"]

    def test_legacy_entry_backfilled_on_read(self, tmp_path: Path) -> None:
        """Legacy entries without id/created_at get backfilled on read_profile."""
        store = MemoryStore(tmp_path)
        # Write a legacy profile (no id, no created_at).
        legacy = {
            "stable_facts": ["User uses Python"],
            "preferences": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "meta": {
                "stable_facts": {
                    "user uses python": {
                        "text": "User uses Python",
                        "confidence": 0.8,
                        "evidence_count": 3,
                        "status": "active",
                        "last_seen_at": "2026-01-01T00:00:00+00:00",
                    }
                }
            },
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        store.profile_mgr.write_profile(legacy)

        profile = store.profile_mgr.read_profile()
        entry = profile["meta"]["stable_facts"]["user uses python"]
        assert "id" in entry
        assert entry["id"].startswith("bf-")
        assert "created_at" in entry

    def test_touch_preserves_id(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        entry = store.profile_mgr._meta_entry(profile, "preferences", "prefers dark mode")
        original_id = entry["id"]

        store.profile_mgr._touch_meta_entry(entry, confidence_delta=0.1)
        assert entry["id"] == original_id


# ---------------------------------------------------------------------------
# LAN-199: Pinned section protection in MEMORY.md
# ---------------------------------------------------------------------------


class TestPinnedSectionProtection:
    def test_extract_pinned_section(self) -> None:
        text = (
            "# Memory\n"
            "<!-- user-pinned -->\n"
            "Critical info.\n"
            "<!-- end-user-pinned -->\n"
            "Other content.\n"
        )
        pinned = MemorySnapshot._extract_pinned_section(text)
        assert pinned is not None
        assert "Critical info." in pinned
        assert pinned.startswith("<!-- user-pinned -->")
        assert pinned.endswith("<!-- end-user-pinned -->")

    def test_extract_returns_none_when_no_fence(self) -> None:
        assert MemorySnapshot._extract_pinned_section("# Memory\nNo fence here.") is None

    def test_extract_returns_none_when_malformed(self) -> None:
        # End before start.
        text = "<!-- end-user-pinned -->\n<!-- user-pinned -->"
        assert MemorySnapshot._extract_pinned_section(text) is None

    def test_restore_inserts_pinned_into_new_content(self) -> None:
        pinned = "<!-- user-pinned -->\nKeep this.\n<!-- end-user-pinned -->"
        new_text = "# Memory\nNew LLM content."
        result = MemorySnapshot._restore_pinned_section(new_text, pinned)
        assert "Keep this." in result
        assert "New LLM content." in result

    def test_restore_replaces_existing_fence(self) -> None:
        pinned = "<!-- user-pinned -->\nUpdated.\n<!-- end-user-pinned -->"
        new_text = "# Memory\n<!-- user-pinned -->\nOld.\n<!-- end-user-pinned -->\nOther."
        result = MemorySnapshot._restore_pinned_section(new_text, pinned)
        assert "Updated." in result
        assert "Old." not in result
        assert "Other." in result

    def test_apply_save_memory_ignores_memory_update(self, tmp_path: Path) -> None:
        """LAN-206: _apply_save_memory_tool_result no longer writes MEMORY.md."""
        store = MemoryStore(tmp_path)
        current = (
            "# Memory\n<!-- user-pinned -->\nDO NOT DELETE\n<!-- end-user-pinned -->\nOld summary."
        )
        store._consolidation._apply_save_memory_tool_result(
            args={"memory_update": "# Memory\nNew summary from LLM."},
            current_memory=current,
        )
        # memory_update should be ignored — snapshot is not written
        written = store.db.read_snapshot("current") if store.db else ""
        assert written == ""

    def test_rebuild_memory_snapshot_preserves_pinned(self, tmp_path: Path) -> None:
        """LAN-206: rebuild_memory_snapshot preserves user-pinned sections."""
        store = MemoryStore(tmp_path)
        pinned_content = (
            "# Memory\n"
            "<!-- user-pinned -->\nDO NOT DELETE\n<!-- end-user-pinned -->\n"
            "Old summary.\n"
        )
        if store.db:
            store.db.write_snapshot("current", pinned_content)
        snapshot = store.snapshot.rebuild_memory_snapshot(write=True)
        assert "DO NOT DELETE" in snapshot
        written = store.db.read_snapshot("current") if store.db else ""
        assert "DO NOT DELETE" in written


# ---------------------------------------------------------------------------
# LAN-197: Evidence event ID linking
# ---------------------------------------------------------------------------


class TestEvidenceLinking:
    def test_touch_appends_evidence_event_id(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        entry = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Python")
        assert entry.get("evidence_event_ids", []) == []

        store.profile_mgr._touch_meta_entry(
            entry, confidence_delta=0.05, evidence_event_id="evt-001"
        )
        assert entry["evidence_event_ids"] == ["evt-001"]

    def test_touch_does_not_duplicate_evidence(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        entry = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Python")

        store.profile_mgr._touch_meta_entry(
            entry, confidence_delta=0.05, evidence_event_id="evt-001"
        )
        store.profile_mgr._touch_meta_entry(
            entry, confidence_delta=0.03, evidence_event_id="evt-001"
        )
        assert entry["evidence_event_ids"] == ["evt-001"]

    def test_evidence_list_capped(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        entry = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Python")

        for i in range(15):
            store.profile_mgr._touch_meta_entry(
                entry, confidence_delta=0.01, evidence_event_id=f"evt-{i:03d}"
            )
        refs = entry["evidence_event_ids"]
        assert len(refs) == store._MAX_EVIDENCE_REFS
        # Most recent should be present.
        assert "evt-014" in refs

    def test_apply_profile_updates_threads_event_ids(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        store.profile_mgr._apply_profile_updates(
            profile,
            {"stable_facts": ["User prefers vim"]},
            enable_contradiction_check=False,
            source_event_ids=["evt-042"],
        )
        entry = profile["meta"]["stable_facts"]["user prefers vim"]
        assert "evt-042" in entry.get("evidence_event_ids", [])


# ---------------------------------------------------------------------------
# LAN-198: Supersession chains + belief IDs in conflict records
# ---------------------------------------------------------------------------


class TestSupersessionChains:
    def test_conflict_record_includes_belief_ids(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        # Seed an existing fact.
        profile["stable_facts"] = ["User does not use dark mode for coding"]
        store.profile_mgr._meta_entry(
            profile, "stable_facts", "User does not use dark mode for coding"
        )

        store.profile_mgr._apply_profile_updates(
            profile,
            {"stable_facts": ["User does use dark mode for coding"]},
            enable_contradiction_check=True,
        )
        conflicts = profile.get("conflicts", [])
        assert len(conflicts) >= 1
        c = conflicts[-1]
        assert "belief_id_old" in c
        assert "belief_id_new" in c
        assert c["belief_id_old"].startswith("bf-")
        assert c["belief_id_new"].startswith("bf-")

    def test_keep_new_sets_supersession(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["stable_facts"] = ["User does not use dark mode for coding"]
        store.profile_mgr._meta_entry(
            profile, "stable_facts", "User does not use dark mode for coding"
        )

        store.profile_mgr._apply_profile_updates(
            profile,
            {"stable_facts": ["User does use dark mode for coding"]},
            enable_contradiction_check=True,
        )
        store.profile_mgr.write_profile(profile)

        # Resolve with keep_new.
        result = store.conflict_mgr.resolve_conflict_details(0, "keep_new")
        assert result["ok"]

        profile = store.profile_mgr.read_profile()
        old_meta = profile["meta"]["stable_facts"].get("user does not use dark mode for coding", {})
        new_meta = profile["meta"]["stable_facts"].get("user does use dark mode for coding", {})

        assert old_meta.get("status") == "stale"
        assert old_meta.get("superseded_by_id") == new_meta.get("id")
        assert new_meta.get("supersedes_id") == old_meta.get("id")


# ---------------------------------------------------------------------------
# LAN-209: Evidence-quality based verification
# ---------------------------------------------------------------------------


class TestVerifyBeliefs:
    def test_empty_profile_returns_zero_summary(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        report = store.profile_mgr.verify_beliefs()
        assert report["summary"]["total"] == 0
        assert report["summary"]["healthy"] == 0
        assert report["summary"]["weak"] == 0
        assert report["summary"]["contradicted"] == 0
        assert report["summary"]["stale"] == 0

    def test_single_new_belief_classified_weak(self, tmp_path: Path) -> None:
        """A brand-new belief with default confidence and evidence_count=1 is weak."""
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["stable_facts"] = ["User uses Python"]
        store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Python")
        store.profile_mgr.write_profile(profile)

        report = store.profile_mgr.verify_beliefs()
        assert report["summary"]["weak"] == 1
        assert report["summary"]["healthy"] == 0
        assert report["weak"][0]["field"] == "stable_facts"

    def test_well_evidenced_belief_classified_healthy(self, tmp_path: Path) -> None:
        """A belief with high confidence and multiple evidence counts is healthy."""
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["preferences"] = ["prefers dark mode"]
        entry = store.profile_mgr._meta_entry(profile, "preferences", "prefers dark mode")
        entry["confidence"] = 0.85
        entry["evidence_count"] = 5
        entry["evidence_event_ids"] = ["evt-1", "evt-2", "evt-3", "evt-4", "evt-5"]
        entry["status"] = "active"
        store.profile_mgr.write_profile(profile)

        report = store.profile_mgr.verify_beliefs()
        assert report["summary"]["healthy"] == 1
        assert report["healthy"][0]["confidence"] == 0.85

    def test_conflicted_belief_classified_contradicted(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["stable_facts"] = ["User likes cats"]
        entry = store.profile_mgr._meta_entry(profile, "stable_facts", "User likes cats")
        entry["status"] = "conflicted"
        entry["confidence"] = 0.5
        entry["evidence_count"] = 3
        store.profile_mgr.write_profile(profile)

        report = store.profile_mgr.verify_beliefs()
        assert report["summary"]["contradicted"] == 1
        assert report["contradicted"][0]["reason"] == "has open conflict"

    def test_superseded_belief_classified_stale(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["stable_facts"] = ["User uses vim"]
        entry = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses vim")
        entry["superseded_by_id"] = "bf-aaaaaaaa"
        entry["status"] = "active"
        entry["confidence"] = 0.9
        entry["evidence_count"] = 10
        store.profile_mgr.write_profile(profile)

        report = store.profile_mgr.verify_beliefs()
        assert report["summary"]["stale"] == 1
        assert report["stale"][0]["reason"] == "superseded or retracted"

    def test_retracted_status_classified_stale(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["constraints"] = ["no shellfish"]
        entry = store.profile_mgr._meta_entry(profile, "constraints", "no shellfish")
        entry["status"] = "retracted"
        store.profile_mgr.write_profile(profile)

        report = store.profile_mgr.verify_beliefs()
        assert report["summary"]["stale"] == 1

    def test_low_confidence_classified_weak(self, tmp_path: Path) -> None:
        """Even with multiple evidence, low confidence => weak."""
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["stable_facts"] = ["User likes tea"]
        entry = store.profile_mgr._meta_entry(profile, "stable_facts", "User likes tea")
        entry["confidence"] = 0.3
        entry["evidence_count"] = 5
        store.profile_mgr.write_profile(profile)

        report = store.profile_mgr.verify_beliefs()
        assert report["summary"]["weak"] == 1

    def test_verify_memory_includes_belief_quality(self, tmp_path: Path) -> None:
        """verify_memory report should include a belief_quality summary."""
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["stable_facts"] = ["User uses Rust"]
        entry = store.profile_mgr._meta_entry(profile, "stable_facts", "User uses Rust")
        entry["confidence"] = 0.9
        entry["evidence_count"] = 4
        store.profile_mgr.write_profile(profile)

        report = store.snapshot.verify_memory()
        assert "belief_quality" in report
        assert report["belief_quality"]["healthy"] == 1

    def test_mixed_beliefs_all_buckets(self, tmp_path: Path) -> None:
        """Profile with beliefs in every bucket produces correct summary."""
        store = MemoryStore(tmp_path)
        profile = store.profile_mgr.read_profile()

        # healthy: high confidence + evidence
        profile["preferences"] = ["dark mode"]
        e = store.profile_mgr._meta_entry(profile, "preferences", "dark mode")
        e["confidence"] = 0.88
        e["evidence_count"] = 3

        # weak: low evidence
        profile["stable_facts"] = ["uses Python"]
        e2 = store.profile_mgr._meta_entry(profile, "stable_facts", "uses Python")
        e2["confidence"] = 0.65
        e2["evidence_count"] = 1

        # contradicted
        profile["constraints"] = ["no dairy"]
        e3 = store.profile_mgr._meta_entry(profile, "constraints", "no dairy")
        e3["status"] = "conflicted"
        e3["confidence"] = 0.5
        e3["evidence_count"] = 3

        # stale
        profile["relationships"] = ["knows Alice"]
        e4 = store.profile_mgr._meta_entry(profile, "relationships", "knows Alice")
        e4["status"] = "retracted"

        store.profile_mgr.write_profile(profile)

        report = store.profile_mgr.verify_beliefs()
        s = report["summary"]
        assert s["healthy"] == 1
        assert s["weak"] == 1
        assert s["contradicted"] == 1
        assert s["stale"] == 1
        assert s["total"] == 4
