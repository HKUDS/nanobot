"""Tests for nanobot.agent.mgp.parsers — bullet and dream-tag parsing.

These tests have no MGP dependency: parsers operate on plain strings and
return plain dataclasses. They cover the prompt-shape contracts encoded in
nanobot's existing ``consolidator_archive.md`` and ``dream_phase1.md`` so a
prompt change that breaks these tests is a deliberate signal, not a regression.
"""

from __future__ import annotations

from nanobot.agent.mgp.parsers import (
    DREAM_TAG_TO_MGP,
    parse_consolidator_bullets,
    parse_dream_phase1_tags,
)


# ---------------------------------------------------------------------------
# parse_consolidator_bullets
# ---------------------------------------------------------------------------


class TestParseConsolidatorBullets:
    def test_empty_input_returns_empty(self) -> None:
        assert parse_consolidator_bullets("") == []
        assert parse_consolidator_bullets("   \n\n  ") == []

    def test_nothing_sentinel_returns_empty(self) -> None:
        assert parse_consolidator_bullets("(nothing)") == []
        # Whitespace + casing tolerated.
        assert parse_consolidator_bullets("  (Nothing)  \n") == []

    def test_raw_archive_marker_returns_empty(self) -> None:
        # raw_archive() output should NOT be propagated to MGP.
        raw = "[RAW] 12 messages\n[2026-04-21 10:00] USER: hello"
        assert parse_consolidator_bullets(raw) == []

    def test_dash_bullets_become_facts(self) -> None:
        summary = "- User has a cat named Luna\n- Project codename is Atlas"
        facts = parse_consolidator_bullets(summary)
        assert len(facts) == 2
        assert facts[0].statement == "User has a cat named Luna"
        assert facts[1].statement == "Project codename is Atlas"
        # Default classification: user / semantic_fact.
        assert all(f.scope == "user" for f in facts)
        assert all(f.type == "semantic_fact" for f in facts)

    def test_other_bullet_styles_supported(self) -> None:
        summary = "* one\n+ two\n1. three\n2) four"
        facts = parse_consolidator_bullets(summary)
        statements = [f.statement for f in facts]
        assert statements == ["one", "two", "three", "four"]

    def test_preference_classification(self) -> None:
        summary = "- User prefers concise replies"
        [fact] = parse_consolidator_bullets(summary)
        assert fact.type == "preference"
        assert fact.preference_value is not None
        assert "concise replies" in fact.preference_value.lower()

    def test_event_classification(self) -> None:
        summary = "- Meeting scheduled for tomorrow morning"
        [fact] = parse_consolidator_bullets(summary)
        assert fact.type == "episodic_event"

    def test_markdown_headers_dropped(self) -> None:
        summary = "## User facts\n- Alice lives in Tokyo\n# Decisions\n- Switched to postgres"
        facts = parse_consolidator_bullets(summary)
        statements = [f.statement for f in facts]
        assert statements == ["Alice lives in Tokyo", "Switched to postgres"]

    def test_blank_lines_ignored(self) -> None:
        summary = "- one\n\n\n- two\n\n"
        assert len(parse_consolidator_bullets(summary)) == 2

    def test_source_ref_propagated(self) -> None:
        [fact] = parse_consolidator_bullets("- foo", source_ref="cli:direct:test")
        assert fact.source_ref == "cli:direct:test"

    def test_unbulleted_lines_still_treated_as_facts(self) -> None:
        # Some LLMs forget the leading dash. We accept the line as-is rather
        # than silently dropping it.
        summary = "User likes dark mode"
        [fact] = parse_consolidator_bullets(summary)
        assert fact.statement == "User likes dark mode"
        # "likes" matches the preference hint set.
        assert fact.type == "preference"


# ---------------------------------------------------------------------------
# parse_dream_phase1_tags
# ---------------------------------------------------------------------------


class TestParseDreamPhase1Tags:
    def test_empty_input_returns_empty(self) -> None:
        assert parse_dream_phase1_tags("") == []

    def test_skip_sentinel_returns_empty(self) -> None:
        assert parse_dream_phase1_tags("[SKIP]") == []

    def test_three_tag_classes_map_correctly(self) -> None:
        analysis = (
            "[USER] location is Tokyo\n"
            "[MEMORY] project Atlas uses pgvector\n"
            "[SOUL] respond in Chinese unless asked otherwise"
        )
        facts = parse_dream_phase1_tags(analysis)
        by_type = {f.type: f for f in facts}
        assert by_type["preference"].scope == "user"
        assert by_type["preference"].statement == "location is Tokyo"
        assert by_type["semantic_fact"].scope == "agent"
        assert by_type["semantic_fact"].statement == "project Atlas uses pgvector"
        # SOUL maps to "profile" (the closest type in MGP's
        # supported_memory_types — there is no "identity" type).
        assert by_type["profile"].scope == "agent"
        assert by_type["profile"].statement.startswith("respond in Chinese")

    def test_file_remove_lines_ignored(self) -> None:
        # FILE-REMOVE may be supported in a future stage; for MVP we ignore.
        analysis = "[FILE-REMOVE] outdated note\n[USER] real fact"
        facts = parse_dream_phase1_tags(analysis)
        assert [f.statement for f in facts] == ["real fact"]

    def test_skill_lines_ignored(self) -> None:
        # SKILL output goes to local skill files only, not MGP.
        analysis = "[SKILL] foo: bar\n[MEMORY] real"
        facts = parse_dream_phase1_tags(analysis)
        assert [f.statement for f in facts] == ["real"]

    def test_unknown_tags_ignored(self) -> None:
        # Tags outside the mapping are silently dropped (defensive).
        analysis = "[FOO] bar\n[USER] real fact"
        facts = parse_dream_phase1_tags(analysis)
        assert len(facts) == 1
        assert facts[0].statement == "real fact"

    def test_blank_lines_and_garbage_skipped(self) -> None:
        analysis = "\nrandom prose\n[USER] fact one\n   \n[MEMORY] fact two\n"
        facts = parse_dream_phase1_tags(analysis)
        assert len(facts) == 2
        assert {f.statement for f in facts} == {"fact one", "fact two"}

    def test_empty_statement_after_tag_dropped(self) -> None:
        # `[USER]   ` with no payload should not produce a fact.
        analysis = "[USER]   \n[USER] real"
        facts = parse_dream_phase1_tags(analysis)
        assert [f.statement for f in facts] == ["real"]

    def test_source_ref_propagated(self) -> None:
        [fact] = parse_dream_phase1_tags("[USER] foo", source_ref="dream:wks-1")
        assert fact.source_ref == "dream:wks-1"

    def test_mapping_table_is_authoritative(self) -> None:
        # Smoke-test against the public mapping table so future renames
        # surface in the diff.
        assert DREAM_TAG_TO_MGP["USER"] == ("user", "preference")
        assert DREAM_TAG_TO_MGP["MEMORY"] == ("agent", "semantic_fact")
        assert DREAM_TAG_TO_MGP["SOUL"] == ("agent", "profile")
