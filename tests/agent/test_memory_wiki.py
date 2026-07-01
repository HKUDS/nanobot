from __future__ import annotations

from datetime import datetime, timezone

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryStore
from nanobot.agent.memory_wiki import MemoryWikiConcept, MemoryWikiStore
from nanobot.utils.helpers import sync_workspace_templates


def test_wiki_round_trip_preserves_lifecycle_metadata(tmp_path) -> None:
    store = MemoryWikiStore(tmp_path / "memory" / "wiki")

    store.write_concept(
        MemoryWikiConcept(
            id="User Language",
            type="user_preference",
            title="Current response language",
            body="User currently prefers English for technical summaries.",
            tags=["user", "language"],
            source=["history:cursor:12"],
            created_at="2026-06-01T10:00:00Z",
            last_verified_at="2026-06-15T09:00:00Z",
            confidence=0.96,
        )
    )

    concept = store.read_concept("user-language")

    assert concept is not None
    assert concept.id == "user-language"
    assert concept.type == "user_preference"
    assert concept.status == "active"
    assert concept.tags == ["user", "language"]
    assert concept.source == ["history:cursor:12"]
    assert concept.confidence == 0.96
    assert "prefers English" in concept.body


def test_retrieval_omits_invalidated_forgotten_and_expired_concepts(tmp_path) -> None:
    store = MemoryWikiStore(tmp_path / "memory" / "wiki")
    store.write_concept(
        MemoryWikiConcept(
            id="current-port",
            type="project_decision",
            title="Gateway port",
            body="The current gateway port is 8877.",
            tags=["gateway", "port"],
            source=["history:cursor:4"],
        )
    )
    store.write_concept(
        MemoryWikiConcept(
            id="old-port",
            type="project_decision",
            title="Old gateway port",
            body="The gateway port was previously 8765.",
            status="invalidated",
            tags=["gateway", "port"],
            source=["history:cursor:1"],
            superseded_by=["current-port"],
        )
    )
    store.write_concept(
        MemoryWikiConcept(
            id="phone-number",
            type="user_private_data",
            title="Forgotten phone number",
            body="User phone number is 555-0100.",
            status="forgotten",
            tags=["user", "phone"],
            source=["history:cursor:2"],
        )
    )
    store.write_concept(
        MemoryWikiConcept(
            id="expired-demo",
            type="time_bound_fact",
            title="Expired demo date",
            body="Ship the demo on 2026-05-01.",
            tags=["demo", "deadline"],
            source=["history:cursor:3"],
            expires_at="2026-05-02T00:00:00Z",
        )
    )

    context = store.get_context(
        "What is the current gateway port and demo deadline?",
        now=datetime(2026, 6, 17, tzinfo=timezone.utc),
    )

    assert "8877" in context
    assert "history:cursor:4" in context
    assert "8765" not in context
    assert "555-0100" not in context
    assert "2026-05-01" not in context


def test_malformed_wiki_files_are_ignored(tmp_path) -> None:
    store = MemoryWikiStore(tmp_path / "memory" / "wiki")
    store.root.mkdir(parents=True)
    (store.root / "broken.md").write_text("not frontmatter\nnot a concept", encoding="utf-8")
    store.write_concept(
        MemoryWikiConcept(
            id="valid",
            title="Valid concept",
            body="This concept should still load.",
            source=["history:cursor:1"],
        )
    )

    concepts = store.iter_concepts()

    assert [concept.id for concept in concepts] == ["valid"]


def test_memory_store_combines_wiki_and_legacy_memory_without_wiki_files(tmp_path) -> None:
    store = MemoryStore(tmp_path)

    assert store.get_memory_context() == ""

    store.write_memory("Legacy fact remains visible.")
    assert "## Long-term Memory" in store.get_memory_context()
    assert "Legacy fact remains visible." in store.get_memory_context()

    store.wiki.write_concept(
        MemoryWikiConcept(
            id="current-language",
            type="user_preference",
            title="Current language",
            body="User currently prefers English.",
            tags=["language"],
            source=["history:cursor:7"],
        )
    )

    context = store.get_memory_context(query="language")

    assert "## Derived Memory Wiki" in context
    assert "User currently prefers English" in context
    assert "source: history:cursor:7" in context
    assert "## Long-term Memory" in context


def test_context_builder_injects_wiki_when_memory_md_is_template(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sync_workspace_templates(workspace, silent=True)
    builder = ContextBuilder(workspace)
    builder.memory.wiki.write_concept(
        MemoryWikiConcept(
            id="current-language",
            type="user_preference",
            title="Current language",
            body="User currently prefers English.",
            tags=["language"],
            source=["history:cursor:7"],
        )
    )

    prompt = builder.build_system_prompt(memory_query="language")

    assert "# Memory\n\n## Derived Memory Wiki" in prompt
    assert "User currently prefers English" in prompt
    assert "# Memory\n\n## Long-term Memory" not in prompt
    assert "This file is automatically updated by nanobot" not in prompt
