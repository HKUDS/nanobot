"""Tests for M4: section utilities + Pinned section preservation across consolidation.

The Pinned section is the structural answer to "safety facts get smoothed away
by the LLM rewrite". It's restored byte-for-byte after every consolidation —
the LLM's cooperation is hopeful, the post-write restore is firm. See
vault/typed-memory-port-from-openclaw.md.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path)


# ---- section parsing ---------------------------------------------------------


def test_list_sections_picks_up_h2_headings(store: MemoryStore) -> None:
    store.write_long_term("## Facts\n- a\n\n## People\n- b\n\n## Events\n- c\n")
    assert store.list_sections() == ["facts", "people", "events"]


def test_list_sections_strips_annotation_suffix(store: MemoryStore) -> None:
    store.write_long_term("## Pinned (do not compress)\n- a\n")
    assert store.list_sections() == ["pinned"]


def test_list_sections_handles_no_sections(store: MemoryStore) -> None:
    store.write_long_term("free-form notes without headings")
    assert store.list_sections() == []


def test_get_section_returns_body(store: MemoryStore) -> None:
    store.write_long_term("## Facts\n- alpha\n- beta\n\n## People\n- carol\n")
    body = store.get_section("Facts")
    assert "alpha" in body
    assert "beta" in body
    assert "carol" not in body


def test_get_section_case_insensitive(store: MemoryStore) -> None:
    store.write_long_term("## FACTS\n- alpha\n")
    assert store.get_section("facts") is not None
    assert "alpha" in store.get_section("facts")


def test_get_section_missing_returns_none(store: MemoryStore) -> None:
    store.write_long_term("## Facts\n- alpha\n")
    assert store.get_section("nope") is None


# ---- upsert_section ----------------------------------------------------------


def test_upsert_replaces_in_place_preserves_others(store: MemoryStore) -> None:
    store.write_long_term("## Facts\n- old\n\n## People\n- carol\n")
    store.upsert_section("Facts", "- new fact 1\n- new fact 2")
    text = store.read_long_term()
    assert "old" not in text
    assert "new fact 1" in text
    assert "new fact 2" in text
    assert "carol" in text, "other sections must be preserved verbatim"


def test_upsert_appends_new_section_when_absent(store: MemoryStore) -> None:
    store.write_long_term("## Facts\n- alpha\n")
    store.upsert_section("Events", "- event 1")
    text = store.read_long_term()
    assert "## Facts" in text
    assert "alpha" in text
    assert "## Events" in text
    assert "event 1" in text


def test_upsert_into_empty_file(store: MemoryStore) -> None:
    store.upsert_section("Facts", "- alpha")
    text = store.read_long_term()
    assert text.startswith("## Facts")
    assert "alpha" in text


def test_upsert_preserves_preamble(store: MemoryStore) -> None:
    store.write_long_term("# Long-term Memory\n\nIntro paragraph.\n\n## Facts\n- alpha\n")
    store.upsert_section("Facts", "- beta")
    text = store.read_long_term()
    assert "# Long-term Memory" in text
    assert "Intro paragraph" in text
    assert "alpha" not in text
    assert "beta" in text


def test_upsert_custom_heading_line(store: MemoryStore) -> None:
    """Annotation in heading must round-trip."""
    store.upsert_section("Pinned", "- safety fact", heading_line="## Pinned (do not compress)")
    text = store.read_long_term()
    assert "## Pinned (do not compress)" in text


# ---- append_to_section -------------------------------------------------------


def test_append_to_existing_section(store: MemoryStore) -> None:
    store.write_long_term("## Facts\n- alpha\n")
    store.append_to_section("Facts", "- beta")
    body = store.get_section("Facts")
    assert "alpha" in body
    assert "beta" in body


def test_append_to_missing_section_creates_it(store: MemoryStore) -> None:
    store.append_to_section("Events", "- event 1")
    assert "event 1" in store.get_section("Events")


# ---- Pinned preservation across consolidation --------------------------------


@pytest.mark.asyncio
async def test_consolidate_restores_pinned_verbatim_even_if_llm_modifies_it(store: MemoryStore) -> None:
    """The structural guarantee: even if the LLM rewrites or drops the Pinned
    section, it's restored byte-for-byte from the pre-call snapshot."""
    from nanobot.session.manager import Session

    pinned_body = (
        "- Safety plan: ~/vault/glyn-safety-plan.md\n"
        "- Triggers: flashbacks, stress\n"
        "- Coping: 4-2-6 breathing, 5-4-3-2-1, NO smell-based grounding (anosmia)\n"
        "- Emergency contact: Steve via Telegram 8775031757"
    )
    initial = (
        "# Long-term Memory\n\n"
        "## Pinned (do not compress)\n"
        f"{pinned_body}\n\n"
        "## Facts\n"
        "- Glyn enjoys film\n"
    )
    store.write_long_term(initial)

    session = Session(key="telegram:test")
    for i in range(40):
        session.add_message("user" if i % 2 else "assistant", f"msg {i}")

    # Provider returns a tool call where the LLM has *modified* the Pinned section
    # — exactly the failure we're protecting against.
    response = MagicMock()
    response.has_tool_calls = True
    tool_call = MagicMock()
    tool_call.arguments = {
        "history_entry": "[2026-05-28] consolidation",
        "memory_update": (
            "## Pinned (do not compress)\n"
            "- Safety plan: somewhere\n"  # LLM "smoothed away" the specifics
            "- Triggers: stress\n"  # dropped flashbacks
            "\n## Facts\n"
            "- Glyn enjoys film and travel\n"
        ),
    }
    response.tool_calls = [tool_call]
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=response)

    ok = await store.consolidate(session, provider, "test-model", memory_window=20)
    assert ok is True

    # Pinned section restored byte-for-byte
    pinned_after = store.get_pinned().strip()
    assert pinned_after == pinned_body.strip()
    assert "Safety plan: ~/vault/glyn-safety-plan.md" in pinned_after
    assert "flashbacks" in pinned_after
    assert "NO smell-based grounding (anosmia)" in pinned_after

    # Heading annotation preserved
    assert "## Pinned (do not compress)" in store.read_long_term()

    # Non-pinned sections take the LLM's update
    facts_after = store.get_section("Facts")
    assert "Glyn enjoys film and travel" in facts_after


@pytest.mark.asyncio
async def test_consolidate_with_no_pinned_section_is_unaffected(store: MemoryStore) -> None:
    """When no Pinned section exists, behaviour is the pre-M4 status quo."""
    from nanobot.session.manager import Session

    store.write_long_term("## Facts\n- alpha\n")
    session = Session(key="telegram:test")
    for i in range(40):
        session.add_message("user" if i % 2 else "assistant", f"msg {i}")

    response = MagicMock()
    response.has_tool_calls = True
    tool_call = MagicMock()
    tool_call.arguments = {
        "history_entry": "[2026-05-28] consolidation",
        "memory_update": "## Facts\n- alpha\n- beta\n",
    }
    response.tool_calls = [tool_call]
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=response)

    ok = await store.consolidate(session, provider, "test-model", memory_window=20)
    assert ok is True
    text = store.read_long_term()
    assert "alpha" in text
    assert "beta" in text


# ---- MEMORY_SCHEMA.md is in the bootstrap files ------------------------------


def test_memory_schema_is_a_bootstrap_file() -> None:
    """MEMORY_SCHEMA.md should be auto-loaded into the system prompt like USER.md."""
    from nanobot.agent.context import ContextBuilder
    assert "MEMORY_SCHEMA.md" in ContextBuilder.BOOTSTRAP_FILES


def test_memory_schema_is_protected() -> None:
    """Agent's edit_file / write_file tools must not be able to modify MEMORY_SCHEMA.md."""
    from nanobot.agent.loop import AgentLoop
    assert "MEMORY_SCHEMA.md" in AgentLoop._PROTECTED_FILES
