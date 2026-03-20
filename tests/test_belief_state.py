"""Tests for the belief state layer: stable IDs, pinned sections, evidence linking."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.memory import MemoryStore

# ---------------------------------------------------------------------------
# LAN-196: Stable IDs for profile item metadata
# ---------------------------------------------------------------------------


class TestStableBeliefIds:
    def test_new_meta_entry_has_id_and_created_at(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.read_profile()
        entry = store._meta_entry(profile, "stable_facts", "User uses Python")

        assert "id" in entry
        assert entry["id"].startswith("bf-")
        assert len(entry["id"]) == 11  # "bf-" + 8 hex chars
        assert "created_at" in entry
        assert entry["created_at"]  # non-empty

    def test_stable_id_is_deterministic(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.read_profile()
        entry = store._meta_entry(profile, "stable_facts", "User uses Python")
        first_id = entry["id"]

        # Re-reading the same entry returns the same ID.
        entry2 = store._meta_entry(profile, "stable_facts", "User uses Python")
        assert entry2["id"] == first_id

    def test_different_items_get_different_ids(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.read_profile()
        e1 = store._meta_entry(profile, "stable_facts", "User uses Python")
        e2 = store._meta_entry(profile, "stable_facts", "User uses Rust")
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
        store.persistence.write_json(store.profile_file, legacy)

        profile = store.read_profile()
        entry = profile["meta"]["stable_facts"]["user uses python"]
        assert "id" in entry
        assert entry["id"].startswith("bf-")
        assert "created_at" in entry

    def test_touch_preserves_id(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        profile = store.read_profile()
        entry = store._meta_entry(profile, "preferences", "prefers dark mode")
        original_id = entry["id"]

        store._touch_meta_entry(entry, confidence_delta=0.1)
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
        pinned = MemoryStore._extract_pinned_section(text)
        assert pinned is not None
        assert "Critical info." in pinned
        assert pinned.startswith("<!-- user-pinned -->")
        assert pinned.endswith("<!-- end-user-pinned -->")

    def test_extract_returns_none_when_no_fence(self) -> None:
        assert MemoryStore._extract_pinned_section("# Memory\nNo fence here.") is None

    def test_extract_returns_none_when_malformed(self) -> None:
        # End before start.
        text = "<!-- end-user-pinned -->\n<!-- user-pinned -->"
        assert MemoryStore._extract_pinned_section(text) is None

    def test_restore_inserts_pinned_into_new_content(self) -> None:
        pinned = "<!-- user-pinned -->\nKeep this.\n<!-- end-user-pinned -->"
        new_text = "# Memory\nNew LLM content."
        result = MemoryStore._restore_pinned_section(new_text, pinned)
        assert "Keep this." in result
        assert "New LLM content." in result

    def test_restore_replaces_existing_fence(self) -> None:
        pinned = "<!-- user-pinned -->\nUpdated.\n<!-- end-user-pinned -->"
        new_text = "# Memory\n<!-- user-pinned -->\nOld.\n<!-- end-user-pinned -->\nOther."
        result = MemoryStore._restore_pinned_section(new_text, pinned)
        assert "Updated." in result
        assert "Old." not in result
        assert "Other." in result

    def test_apply_save_memory_preserves_pinned(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path)
        current = (
            "# Memory\n<!-- user-pinned -->\nDO NOT DELETE\n<!-- end-user-pinned -->\nOld summary."
        )
        store._apply_save_memory_tool_result(
            args={"memory_update": "# Memory\nNew summary from LLM."},
            current_memory=current,
        )
        written = store.read_long_term()
        assert "DO NOT DELETE" in written
        assert "New summary from LLM." in written
