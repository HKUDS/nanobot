"""Additional branch tests for MemoryStore to raise module coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _store(tmp_path: Path, **overrides: object) -> MemoryStore:
    return MemoryStore(tmp_path, rollout_overrides=overrides or None, embedding_provider="hash")


class TestReindexBranches:
    def test_reindex_mem0_disabled(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.mem0.enabled = False
        out = store.reindex_from_structured_memory()
        assert out["ok"] is False
        assert out["reason"] == "mem0_disabled"

    def test_reindex_reset_failure(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.mem0.enabled = True
        store.mem0.delete_all_user_memories = MagicMock(return_value=(False, "boom", 0))

        out = store.reindex_from_structured_memory(reset_existing=True)
        assert out["ok"] is False
        assert out["reason"] == "structured_reindex_reset_failed"

    def test_reindex_success_with_compaction(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
        profile["preferences"] = ["Use Python", "Use Python"]
        store.write_profile(profile)
        store.persistence.write_jsonl(
            store.events_file,
            [
                {
                    "id": "e1",
                    "type": "fact",
                    "summary": "Project uses OAuth2",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "entities": ["project", "oauth2"],
                },
                {
                    "id": "e2",
                    "type": "fact",
                    "summary": "Project uses OAuth2",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "entities": ["project", "oauth2"],
                },
            ],
        )

        store.mem0.enabled = True
        store.mem0.delete_all_user_memories = MagicMock(return_value=(True, "", 2))
        store.mem0.add_text = MagicMock(return_value=True)
        store.mem0.flush_vector_store = MagicMock(return_value=True)
        store.mem0.reopen_client = MagicMock(return_value=None)
        store.mem0.last_add_mode = "vector"
        store._vector_points_count = MagicMock(return_value=2)
        store._mem0_get_all_rows = MagicMock(return_value=[{"id": "x"}])

        out = store.reindex_from_structured_memory(reset_existing=True, compact=True)
        assert out["ok"] is True
        assert out["written"] >= 1
        assert out["flush_applied"] is True

    def test_seed_structured_corpus_invalid_profile(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile_path = tmp_path / "profile.json"
        events_path = tmp_path / "events.jsonl"
        profile_path.write_text("[]", encoding="utf-8")
        events_path.write_text("", encoding="utf-8")

        out = store.seed_structured_corpus(profile_path=profile_path, events_path=events_path)
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

        store.mem0.enabled = True
        store.mem0.delete_all_user_memories = MagicMock(return_value=(True, "", 0))
        store.mem0.add_text = MagicMock(return_value=True)
        store.mem0.flush_vector_store = MagicMock(return_value=False)
        store.mem0.reopen_client = MagicMock(return_value=None)
        store.mem0.last_add_mode = "history"
        store._vector_points_count = MagicMock(return_value=1)
        store._mem0_get_all_rows = MagicMock(return_value=[{"id": "m"}])

        out = store.seed_structured_corpus(profile_path=profile_path, events_path=events_path)
        assert out["ok"] is True
        assert out["seeded_events"] >= 1


class TestVectorHealthBranches:
    def test_vector_health_disabled_and_mem0_disabled(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.rollout["memory_vector_health_enabled"] = False
        store._ensure_vector_health()

        store.rollout["memory_vector_health_enabled"] = True
        store.mem0.enabled = False
        store._ensure_vector_health()

    def test_vector_health_degraded_no_auto_reindex(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.mem0.enabled = True
        store.mem0.search = MagicMock(return_value=[])
        store.rollout["memory_auto_reindex_on_empty_vector"] = False
        store._mem0_get_all_rows = MagicMock(return_value=[])
        store._vector_points_count = MagicMock(return_value=0)
        store._history_row_count = MagicMock(return_value=10)

        store.reindex_from_structured_memory = MagicMock()  # type: ignore[method-assign]

        store._ensure_vector_health()
        store.reindex_from_structured_memory.assert_not_called()


class TestConsolidationHelpers:
    def test_select_messages_for_consolidation_paths(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        session = SimpleNamespace(messages=[], last_consolidated=0)
        assert (
            store._select_messages_for_consolidation(session, archive_all=False, memory_window=10)
            is None
        )

        session = SimpleNamespace(
            messages=[{"role": "user", "content": f"m{i}"} for i in range(12)],
            last_consolidated=11,
        )
        assert (
            store._select_messages_for_consolidation(session, archive_all=False, memory_window=10)
            is None
        )

        session = SimpleNamespace(
            messages=[
                {"role": "user", "content": f"m{i}", "timestamp": "2026-01-01"} for i in range(12)
            ],
            last_consolidated=0,
        )
        selected = store._select_messages_for_consolidation(
            session, archive_all=False, memory_window=10
        )
        assert selected is not None

        selected_all = store._select_messages_for_consolidation(
            session, archive_all=True, memory_window=10
        )
        assert selected_all is not None

    def test_format_prompt_and_save_tool_result(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        lines = store._format_conversation_lines(
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
        prompt = store._build_consolidation_prompt("# Memory", lines)
        assert "Current Long-term Memory" in prompt

        store._apply_save_memory_tool_result(
            args={"history_entry": {"x": 1}, "memory_update": {"y": 2}}, current_memory=""
        )
        assert store.history_file.exists()
        assert store.memory_file.exists()

    async def test_consolidate_no_tool_call(self, tmp_path: Path) -> None:
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
        assert ok is False

    async def test_consolidate_parsing_failure(self, tmp_path: Path) -> None:
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
                    ToolCallRequest(id="x", name="save_memory", arguments={"bad": object()})
                ],
            )
        )
        store.extractor.parse_tool_args = MagicMock(return_value=None)

        ok = await store.consolidate(session, provider, model="m", memory_window=10)
        assert ok is False

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
        profile = store.read_profile()
        profile["preferences"] = ["dark mode"]
        profile["meta"]["preferences"] = {
            "dark mode": {
                "confidence": 0.7,
                "status": "active",
                "first_seen_at": "2020-01-01T00:00:00+00:00",
                "last_seen_at": "2020-01-01T00:00:00+00:00",
            }
        }
        store.write_profile(profile)
        store.persistence.write_jsonl(
            store.events_file,
            [
                {
                    "type": "fact",
                    "summary": "old",
                    "timestamp": "2020-01-01T00:00:00+00:00",
                    "ttl_days": 1,
                }
            ],
        )

        report = store.verify_memory(stale_days=30, update_profile=True)
        assert report["stale_events"] >= 1

    def test_get_memory_context_minimal_and_empty_query(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        text = store.get_memory_context(query="", token_budget=200)
        assert isinstance(text, str)

    def test_apply_live_user_correction_no_match(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        out = store.apply_live_user_correction("hello there", channel="cli", chat_id="x")
        assert isinstance(out, dict)

    def test_apply_live_user_correction_with_conflict_and_mem0_write(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
        profile["preferences"] = ["Use dark mode"]
        profile["stable_facts"] = ["Project uses Flask"]
        store.write_profile(profile)

        store.extractor.extract_explicit_preference_corrections = MagicMock(
            return_value=[("Do not use dark mode", "Use dark mode")]
        )
        store.extractor.extract_explicit_fact_corrections = MagicMock(
            return_value=[("Project uses FastAPI", "Project uses Flask")]
        )
        store.mem0.enabled = True
        store.mem0.add_text = MagicMock(return_value=True)

        out = store.apply_live_user_correction(
            "Actually, not dark mode and not Flask anymore.",
            channel="cli",
            chat_id="direct",
        )
        assert out["events"] >= 1
        assert out["conflicts"] >= 1

    def test_apply_live_user_correction_mem0_failure_branch(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.extractor.extract_explicit_preference_corrections = MagicMock(
            return_value=[("Use light mode", "Use dark mode")]
        )
        store.extractor.extract_explicit_fact_corrections = MagicMock(return_value=[])
        store.mem0.enabled = True
        store.mem0.add_text = MagicMock(return_value=False)

        out = store.apply_live_user_correction(
            "I use light mode now, not dark mode.",
            channel="cli",
            chat_id="direct",
        )
        assert isinstance(out, dict)


class TestConsolidationMem0Path:
    async def test_consolidate_success_with_mem0_turn_writes(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.mem0.enabled = True
        store.mem0.add_text = MagicMock(return_value=True)
        store.mem0.last_add_mode = "vector"

        session = SimpleNamespace(
            key="mem0-session",
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
        assert store._merge_source_span([3, 5], [1, 4]) == [1, 5]
        assert store._merge_source_span("bad", [2, 3]) == [0, 3]

        event = {
            "type": "fact",
            "summary": "No id event",
            "source": "chat",
        }
        out = store._ensure_event_provenance(event)
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
        idx, score = store._find_semantic_duplicate(candidate, existing)
        assert idx == 0
        assert score > 0

        candidate2 = {
            "id": "c2",
            "type": "fact",
            "summary": "User does not prefer dark mode",
            "entities": ["user", "dark mode"],
            "memory_type": "semantic",
        }
        sup_idx = store._find_semantic_supersession(candidate2, existing)
        assert sup_idx == 0

    async def test_ingest_graph_triples_enabled(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.graph.enabled = True
        store.graph.ingest_event_triples = AsyncMock(return_value=None)

        total = await store._ingest_graph_triples(
            [
                {
                    "id": "e1",
                    "timestamp": "2026-03-01T00:00:00+00:00",
                    "triples": [{"subject": "Alice", "predicate": "WORKS_ON", "object": "Nanobot"}],
                }
            ]
        )
        assert total == 1

    def test_find_mem0_id_for_text_tuple_and_fallback(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.mem0.enabled = True
        store.mem0.search = MagicMock(
            return_value=(
                [
                    {"id": "m1", "summary": "unrelated"},
                    {"id": "m2", "summary": "target fact"},
                ],
                {"source_vector": 1},
            )
        )
        out = store._find_mem0_id_for_text("target fact")
        assert out in {"m1", "m2"}

    def test_validate_profile_field_raises(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        with pytest.raises(ValueError):
            store._validate_profile_field("unknown")

    def test_resolve_conflict_details_dismiss_and_mem0_update_fail(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
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
        store.write_profile(profile)

        dismissed = store.resolve_conflict_details(0, "dismiss")
        assert dismissed["ok"] is True

        profile = store.read_profile()
        profile["conflicts"] = [
            {
                "field": "preferences",
                "old": "old",
                "new": "new",
                "status": "open",
                "old_memory_id": "old-id",
            }
        ]
        store.write_profile(profile)
        store.mem0.enabled = True
        store.mem0.update = MagicMock(return_value=False)
        failed = store.resolve_conflict_details(0, "keep_new")
        assert failed["ok"] is False

    def test_build_graph_context_lines_with_graph_and_local_triples(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.extractor._extract_entities = MagicMock(return_value=["Alice"])
        store.graph.enabled = True
        store.graph.get_triples_for_entities_sync = MagicMock(
            return_value=[("Alice", "WORKS_ON", "Nanobot")]
        )
        store.persistence.write_jsonl(
            store.events_file,
            [
                {
                    "id": "e1",
                    "entities": ["alice", "nanobot"],
                    "triples": [
                        {
                            "subject": "Alice",
                            "predicate": "CONTRIBUTES_TO",
                            "object": "Nanobot",
                        }
                    ],
                }
            ],
        )

        lines = store._build_graph_context_lines("alice", [], max_tokens=40)
        assert isinstance(lines, list)
        assert len(lines) >= 1


class TestRetrieveAndContextBranches:
    def test_retrieve_mem0_enabled_mode_disabled(self, tmp_path: Path) -> None:
        store = _store(tmp_path, memory_rollout_mode="disabled")
        store.mem0.enabled = True
        store.mem0.search = MagicMock(
            return_value=(
                [
                    {
                        "id": "m1",
                        "type": "fact",
                        "summary": "Project uses OAuth2",
                        "entities": ["project", "oauth2"],
                        "metadata": {"memory_type": "semantic", "topic": "knowledge"},
                        "score": 0.4,
                    }
                ],
                {
                    "source_vector": 1,
                    "source_get_all": 0,
                    "source_history": 0,
                    "rejected_blob_like": 0,
                },
            )
        )
        out = store.retrieve("oauth2", top_k=3)
        assert isinstance(out, list)
        assert len(out) >= 1

    def test_retrieve_core_empty_results(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.mem0.enabled = True
        store.mem0.search = MagicMock(
            return_value=(
                [],
                {
                    "source_vector": 0,
                    "source_get_all": 0,
                    "source_history": 0,
                    "rejected_blob_like": 0,
                },
            )
        )
        final, stats = store._retrieve_core(
            query="nothing",
            top_k=3,
            router_enabled=True,
            type_separation_enabled=True,
            reflection_enabled=True,
        )
        assert final == []
        assert stats["retrieved_count"] == 0

    def test_retrieve_core_rollout_status_injects_synthetic(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.mem0.enabled = True
        store.mem0.search = MagicMock(
            return_value=(
                [],
                {
                    "source_vector": 0,
                    "source_get_all": 0,
                    "source_history": 0,
                    "rejected_blob_like": 0,
                },
            )
        )
        final, stats = store._retrieve_core(
            query="rollout status",
            top_k=2,
            router_enabled=True,
            type_separation_enabled=True,
            reflection_enabled=True,
        )
        assert len(final) >= 1
        assert any(str(item.get("id", "")).startswith("rollout_status") for item in final)
        assert stats["intent"] == "rollout_status"

    def test_retrieve_core_reflection_filtering(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.mem0.enabled = True
        store.mem0.search = MagicMock(
            return_value=(
                [
                    {
                        "id": "r1",
                        "type": "fact",
                        "summary": "Reflection without evidence",
                        "metadata": {"memory_type": "reflection", "topic": "reflection"},
                        "score": 0.9,
                    }
                ],
                {
                    "source_vector": 1,
                    "source_get_all": 0,
                    "source_history": 0,
                    "rejected_blob_like": 0,
                },
            )
        )
        final, stats = store._retrieve_core(
            query="reflect",
            top_k=3,
            router_enabled=True,
            type_separation_enabled=True,
            reflection_enabled=True,
        )
        assert isinstance(final, list)
        assert stats["counts"]["reflection_filtered_no_evidence"] >= 1

    def test_get_memory_context_with_sections(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.write_long_term("## Long\nProject memory details")
        profile = store.read_profile()
        profile["preferences"] = ["Prefer concise output"]
        store.write_profile(profile)
        store.persistence.write_jsonl(
            store.events_file,
            [
                {
                    "id": "e1",
                    "type": "task",
                    "summary": "Deploy service in progress",
                    "status": "open",
                    "timestamp": "2026-03-10T00:00:00+00:00",
                    "entities": ["deploy"],
                },
                {
                    "id": "e2",
                    "type": "fact",
                    "summary": "Project uses OAuth2",
                    "timestamp": "2026-03-10T00:00:00+00:00",
                    "entities": ["project", "oauth2"],
                },
            ],
        )
        context = store.get_memory_context(query="open tasks", retrieval_k=4, token_budget=300)
        assert isinstance(context, str)
        assert len(context) > 0


class TestConflictResolutionBranches:
    def test_resolve_conflict_keep_old_delete_new(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
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
        store.write_profile(profile)
        store.mem0.delete = MagicMock(return_value=True)

        result = store.resolve_conflict_details(0, "keep_old")
        assert result["ok"] is True
        assert result["mem0_operation"] in {"delete_new", "none"}

    def test_resolve_conflict_keep_new_add_new_path(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
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
        store.write_profile(profile)
        store.mem0.add_text = MagicMock(return_value=True)

        result = store.resolve_conflict_details(0, "keep_new")
        assert result["ok"] is True
        assert result["mem0_operation"] == "add_new"

    def test_resolve_conflict_invalid_action(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
        profile["preferences"] = ["old", "new"]
        profile["conflicts"] = [
            {
                "field": "preferences",
                "old": "old",
                "new": "new",
                "status": "open",
            }
        ]
        store.write_profile(profile)
        result = store.resolve_conflict_details(0, "bad_action")
        assert result["ok"] is False
