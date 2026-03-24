"""Additional branch tests for MemoryStore to raise module coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.agent.memory.ingester import EventIngester
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _store(tmp_path: Path, **overrides: object) -> MemoryStore:
    return MemoryStore(tmp_path, rollout_overrides=overrides or None, embedding_provider="hash")


class TestReindexBranches:
    def test_reindex_returns_unified_db_active(self, tmp_path: Path) -> None:
        """With UnifiedMemoryDB, reindex is a no-op success."""
        store = _store(tmp_path)
        out = store.maintenance.reindex_from_structured_memory(
            read_profile_fn=store.profile_mgr.read_profile,
            read_events_fn=store.ingester.read_events,
            ingester=store.ingester,
            profile_keys=store.PROFILE_KEYS,
        )
        assert out["ok"] is True
        assert out["reason"] == "unified_db_active"

    def test_seed_structured_corpus_invalid_profile(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile_path = tmp_path / "profile.json"
        events_path = tmp_path / "events.jsonl"
        profile_path.write_text("[]", encoding="utf-8")
        events_path.write_text("", encoding="utf-8")

        out = store.maintenance.seed_structured_corpus(
            profile_path=profile_path,
            events_path=events_path,
            read_profile_fn=store.profile_mgr.read_profile,
            write_profile_fn=store.profile_mgr.write_profile,
            read_events_fn=store.ingester.read_events,
            ingester=store.ingester,
            profile_keys=store.PROFILE_KEYS,
        )
        assert out["ok"] is False
        assert "invalid_profile_seed" in out["reason"]

    def test_seed_structured_corpus_success(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile_path = tmp_path / "profile.json"
        events_path = tmp_path / "events.jsonl"
        profile_path.write_text(
            json.dumps(
                {
                    "preferences": ["Prefer concise responses"],
                    "stable_facts": ["Project uses OAuth2"],
                    "active_projects": [],
                    "relationships": [],
                    "constraints": [],
                }
            ),
            encoding="utf-8",
        )
        events_path.write_text(
            json.dumps(
                {
                    "type": "fact",
                    "summary": "Project uses OAuth2",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        out = store.maintenance.seed_structured_corpus(
            profile_path=profile_path,
            events_path=events_path,
            read_profile_fn=store.profile_mgr.read_profile,
            write_profile_fn=store.profile_mgr.write_profile,
            read_events_fn=store.ingester.read_events,
            ingester=store.ingester,
            profile_keys=store.PROFILE_KEYS,
        )
        assert out["ok"] is True
        assert out["seeded_events"] >= 1


class TestConsolidationHelpers:
    def test_select_messages_for_consolidation_paths(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        session = SimpleNamespace(messages=[], last_consolidated=0)
        assert (
            store._consolidation._select_messages_for_consolidation(
                session, archive_all=False, memory_window=10
            )
            is None
        )

        session = SimpleNamespace(
            messages=[{"role": "user", "content": f"m{i}"} for i in range(12)],
            last_consolidated=11,
        )
        assert (
            store._consolidation._select_messages_for_consolidation(
                session, archive_all=False, memory_window=10
            )
            is None
        )

        session = SimpleNamespace(
            messages=[
                {"role": "user", "content": f"m{i}", "timestamp": "2026-01-01"} for i in range(12)
            ],
            last_consolidated=0,
        )
        selected = store._consolidation._select_messages_for_consolidation(
            session, archive_all=False, memory_window=10
        )
        assert selected is not None

        selected_all = store._consolidation._select_messages_for_consolidation(
            session, archive_all=True, memory_window=10
        )
        assert selected_all is not None

    def test_format_conversation_lines(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        pipeline = store._consolidation
        lines = pipeline._format_conversation_lines(
            [
                {
                    "timestamp": "2026-01-01T10:00:00+00:00",
                    "role": "user",
                    "content": "hello",
                    "tools_used": ["read_file"],
                },
                {"timestamp": "2026-01-01T10:00:01+00:00", "role": "assistant", "content": "hi"},
            ]
        )
        assert len(lines) == 2
        # Single-tool prompt includes the conversation lines
        prompt = pipeline._build_single_tool_prompt("# Memory", lines)
        assert "Current Long-term Memory" in prompt

    async def test_consolidate_no_tool_call_uses_fallback(self, tmp_path: Path) -> None:
        """When LLM returns no tool call, single-tool path uses heuristic fallback."""
        store = _store(tmp_path)
        session = SimpleNamespace(
            key="k1",
            messages=[
                {"role": "user", "content": "hello", "timestamp": "2026-01-01"} for _ in range(20)
            ],
            last_consolidated=0,
        )
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=LLMResponse(content="plain text"))

        ok = await store.consolidate(session, provider, model="m", memory_window=10)
        # Single-tool path uses heuristic fallback, so it succeeds.
        assert ok is True

    async def test_consolidate_parsing_failure_uses_fallback(self, tmp_path: Path) -> None:
        """When parse_tool_args returns None, single-tool path uses heuristic fallback."""
        store = _store(tmp_path)
        session = SimpleNamespace(
            key="k2",
            messages=[
                {"role": "user", "content": "hello", "timestamp": "2026-01-01"} for _ in range(20)
            ],
            last_consolidated=0,
        )

        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="x", name="consolidate_memory", arguments={"bad": object()})
                ],
            )
        )
        store.extractor.parse_tool_args = MagicMock(return_value=None)

        ok = await store.consolidate(session, provider, model="m", memory_window=10)
        # Single-tool path uses heuristic fallback when parsing fails.
        assert ok is True

    async def test_consolidate_exception_path(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        session = SimpleNamespace(
            key="k3",
            messages=[
                {"role": "user", "content": "hello", "timestamp": "2026-01-01"} for _ in range(20)
            ],
            last_consolidated=0,
        )
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=RuntimeError("boom"))

        ok = await store.consolidate(session, provider, model="m", memory_window=10)
        assert ok is False


class TestVerifyAndContextBranches:
    def test_verify_memory_update_profile(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["preferences"] = ["dark mode"]
        profile["meta"]["preferences"] = {
            "dark mode": {
                "confidence": 0.7,
                "status": "active",
                "first_seen_at": "2020-01-01T00:00:00+00:00",
                "last_seen_at": "2020-01-01T00:00:00+00:00",
            }
        }
        store.profile_mgr.write_profile(profile)

        events = [
            {
                "id": "ev1",
                "type": "fact",
                "summary": "old",
                "timestamp": "2020-01-01T00:00:00+00:00",
                "ttl_days": 1,
            }
        ]
        if store.db:
            for evt in events:
                store.db.insert_event(evt)

        report = store.snapshot.verify_memory(stale_days=30, update_profile=True)
        assert report["stale_events"] >= 1

    def test_get_memory_context_minimal_and_empty_query(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        text = store.get_memory_context(query="", token_budget=200)
        assert isinstance(text, str)

    def test_apply_live_user_correction_no_match(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        out = store.profile_mgr.apply_live_user_correction(
            "hello there", channel="cli", chat_id="x"
        )
        assert isinstance(out, dict)


class TestConsolidationWithExtraction:
    async def test_consolidate_success_with_extraction(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        session = SimpleNamespace(
            key="extract-session",
            messages=[
                {
                    "role": "user",
                    "content": "I prefer concise output.",
                    "timestamp": "2026-03-10T10:00:00+00:00",
                },
                {
                    "role": "assistant",
                    "content": "Noted.",
                    "timestamp": "2026-03-10T10:00:01+00:00",
                },
            ]
            * 12,
            last_consolidated=0,
        )

        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="save1",
                        name="save_memory",
                        arguments={
                            "history_entry": "Consolidated",
                            "memory_update": "# Memory\nUser prefers concise output.",
                        },
                    )
                ],
            )
        )

        store.extractor.parse_tool_args = MagicMock(
            return_value={"history_entry": "Consolidated", "memory_update": "# Memory\nX"}
        )
        store.extractor.extract_structured_memory = AsyncMock(
            return_value=(
                [
                    {
                        "type": "preference",
                        "summary": "User prefers concise output.",
                        "timestamp": "2026-03-10T10:00:00+00:00",
                        "entities": ["user", "preference"],
                        "salience": 0.9,
                        "confidence": 0.9,
                    }
                ],
                {"preferences": ["User prefers concise output."]},
            )
        )

        ok = await store.consolidate(session, provider, model="m", memory_window=10)
        assert ok is True


class TestStoreCoreBranchHelpers:
    def test_merge_source_span_and_provenance_without_id(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        assert EventIngester._merge_source_span([3, 5], [1, 4]) == [1, 5]
        assert EventIngester._merge_source_span("bad", [2, 3]) == [0, 3]

        event = {
            "type": "fact",
            "summary": "No id event",
            "source": "chat",
        }
        out = store.ingester._ensure_event_provenance(event)
        assert out["memory_type"] in {"semantic", "episodic", "reflection"}
        assert "canonical_id" not in out

    def test_find_semantic_duplicate_and_supersession(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        candidate = {
            "id": "c1",
            "type": "fact",
            "summary": "User prefers dark mode",
            "entities": ["user", "dark mode"],
            "memory_type": "semantic",
        }
        existing = [
            {
                "id": "e1",
                "type": "fact",
                "summary": "User prefers dark mode",
                "entities": ["user", "dark mode"],
                "memory_type": "semantic",
            }
        ]
        idx, score = store.ingester._find_semantic_duplicate(candidate, existing)
        assert idx == 0
        assert score > 0

        candidate2 = {
            "id": "c2",
            "type": "fact",
            "summary": "User does not prefer dark mode",
            "entities": ["user", "dark mode"],
            "memory_type": "semantic",
        }
        sup_idx = store.ingester._find_semantic_supersession(candidate2, existing)
        assert sup_idx == 0

    async def test_ingest_graph_triples_enabled(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.graph.enabled = True
        store.graph.ingest_event_triples = AsyncMock(return_value=None)

        total = await store.ingester._ingest_graph_triples(
            [
                {
                    "id": "e1",
                    "timestamp": "2026-03-01T00:00:00+00:00",
                    "triples": [{"subject": "Alice", "predicate": "WORKS_ON", "object": "Nanobot"}],
                }
            ]
        )
        assert total == 1

    def test_find_mem0_id_for_text_via_fts(self, tmp_path: Path) -> None:
        """_find_mem0_id_for_text searches FTS via UnifiedMemoryDB."""
        store = _store(tmp_path)
        # Insert an event so FTS has something to search
        if store.db:
            store.db.insert_event(
                {
                    "id": "m2",
                    "type": "fact",
                    "summary": "target fact about Python",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                }
            )
        out = store.profile_mgr._find_mem0_id_for_text("target fact")
        # With FTS data, should find a match
        if store.db:
            assert out is not None

    def test_validate_profile_field_raises(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        with pytest.raises(ValueError):
            store.profile_mgr._validate_profile_field("unknown")

    def test_resolve_conflict_details_dismiss(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["preferences"] = ["old", "new"]
        profile["conflicts"] = [
            {
                "field": "preferences",
                "old": "old",
                "new": "new",
                "status": "open",
                "old_memory_id": "old-id",
                "new_memory_id": "new-id",
            }
        ]
        store.profile_mgr.write_profile(profile)

        dismissed = store.conflict_mgr.resolve_conflict_details(0, "dismiss")
        assert dismissed["ok"] is True

    def test_build_graph_context_lines_with_graph(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.extractor._extract_entities = MagicMock(return_value=["Alice"])
        store.graph.enabled = True
        store.graph.get_triples_for_entities_sync = MagicMock(
            return_value=[("Alice", "WORKS_ON", "Nanobot")]
        )
        if store.db:
            store.db.insert_event(
                {
                    "id": "e1",
                    "type": "fact",
                    "summary": "Alice works on Nanobot",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "entities": ["alice", "nanobot"],
                }
            )

        lines = store.retriever._build_graph_context_lines("alice", [], max_tokens=40)
        assert isinstance(lines, list)
        assert len(lines) >= 1


class TestRetrieveAndContextBranches:
    def test_get_memory_context_with_sections(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        if store.db:
            store.db.write_snapshot("current", "## Long\nProject memory details")
        profile = store.profile_mgr.read_profile()
        profile["preferences"] = ["Prefer concise output"]
        store.profile_mgr.write_profile(profile)
        if store.db:
            store.db.insert_event(
                {
                    "id": "e1",
                    "type": "task",
                    "summary": "Deploy service in progress",
                    "status": "open",
                    "timestamp": "2026-03-10T00:00:00+00:00",
                    "entities": ["deploy"],
                }
            )
            store.db.insert_event(
                {
                    "id": "e2",
                    "type": "fact",
                    "summary": "Project uses OAuth2",
                    "timestamp": "2026-03-10T00:00:00+00:00",
                    "entities": ["project", "oauth2"],
                }
            )
        context = store.get_memory_context(query="open tasks", retrieval_k=4, token_budget=300)
        assert isinstance(context, str)
        assert len(context) > 0


class TestConflictResolutionBranches:
    def test_resolve_conflict_keep_old(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["preferences"] = ["old", "new"]
        profile["conflicts"] = [
            {
                "field": "preferences",
                "old": "old",
                "new": "new",
                "status": "open",
                "new_memory_id": "mem-new",
            }
        ]
        store.profile_mgr.write_profile(profile)

        result = store.conflict_mgr.resolve_conflict_details(0, "keep_old")
        assert result["ok"] is True

    def test_resolve_conflict_keep_new_path(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["preferences"] = ["old"]
        profile["conflicts"] = [
            {
                "field": "preferences",
                "old": "old",
                "new": "new",
                "status": "open",
                "old_memory_id": "",
                "new_memory_id": "",
            }
        ]
        store.profile_mgr.write_profile(profile)

        result = store.conflict_mgr.resolve_conflict_details(0, "keep_new")
        assert result["ok"] is True

    def test_resolve_conflict_invalid_action(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.profile_mgr.read_profile()
        profile["preferences"] = ["old", "new"]
        profile["conflicts"] = [
            {
                "field": "preferences",
                "old": "old",
                "new": "new",
                "status": "open",
            }
        ]
        store.profile_mgr.write_profile(profile)
        result = store.conflict_mgr.resolve_conflict_details(0, "bad_action")
        assert result["ok"] is False
