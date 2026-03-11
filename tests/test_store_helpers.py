"""Extra coverage tests for MemoryStore helper and branch-heavy paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.memory import MemoryStore


def _store(tmp_path: Path, **overrides: object) -> MemoryStore:
    return MemoryStore(tmp_path, rollout_overrides=overrides or None, embedding_provider="hash")


def _seed_events(store: MemoryStore, events: list[dict[str, object]]) -> None:
    existing = store.read_events()
    rows = [*existing, *events]
    store.persistence.write_jsonl(store.events_file, rows)


class TestMemoryStoreExtraHelpers:
    def test_env_bool_and_datetime_parsers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NB_BOOL_TRUE", "yes")
        monkeypatch.setenv("NB_BOOL_FALSE", "off")
        monkeypatch.setenv("NB_BOOL_INVALID", "maybe")

        assert MemoryStore._env_bool("NB_BOOL_TRUE") is True
        assert MemoryStore._env_bool("NB_BOOL_FALSE") is False
        assert MemoryStore._env_bool("NB_BOOL_INVALID") is None
        assert MemoryStore._env_bool("NB_BOOL_MISSING") is None

        assert MemoryStore._to_datetime("2026-01-01T00:00:00Z") is not None
        assert MemoryStore._to_datetime("invalid") is None

    def test_rollout_overrides_and_status(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store._apply_rollout_overrides(
            {
                "memory_rollout_mode": "shadow",
                "memory_shadow_mode": True,
                "memory_shadow_sample_rate": 0.9,
                "memory_fallback_allowed_sources": ["events", "profile"],
                "memory_fallback_max_summary_chars": 222,
                "rollout_gates": {"min_recall_at_k": 0.91},
                "reranker_mode": "shadow",
                "reranker_alpha": 0.8,
                "reranker_model": "test-reranker",
            }
        )
        status = store.get_rollout_status()
        assert status["memory_rollout_mode"] == "shadow"
        assert status["memory_shadow_mode"] is True
        assert status["memory_shadow_sample_rate"] == pytest.approx(0.9)
        assert status["memory_fallback_allowed_sources"] == ["events", "profile"]
        assert status["memory_fallback_max_summary_chars"] == 222
        assert status["rollout_gates"]["min_recall_at_k"] == pytest.approx(0.91)
        assert status["reranker_mode"] == "shadow"
        assert status["reranker_alpha"] == pytest.approx(0.8)

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("what failed yesterday", "debug_history"),
            ("reflect on lessons learned", "reflection"),
            ("what is rollout status", "rollout_status"),
            ("open tasks and decisions", "planning"),
            ("what constraints apply", "constraints_lookup"),
            ("any conflict pending", "conflict_review"),
            ("what is user preference", "fact_lookup"),
        ],
    )
    def test_intent_and_routing_hints(self, query: str, expected: str) -> None:
        assert MemoryStore._infer_retrieval_intent(query) == expected
        hints = MemoryStore._query_routing_hints(query)
        assert isinstance(hints, dict)
        assert "focus_planning" in hints

    def test_type_classification_and_metadata_normalization(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        memory_type, stability, is_mixed = store._classify_memory_type(
            event_type="preference",
            summary="User prefers dark mode because setup failed yesterday",
            source="chat",
        )
        assert memory_type == "semantic"
        assert stability in {"medium", "high"}
        assert is_mixed is True

        normalized, mixed_flag = store._normalize_memory_metadata(
            {"memory_type": "reflection", "confidence": 2.0, "ttl_days": -1},
            event_type="fact",
            summary="A reflection without evidence",
            source="reflection",
        )
        assert normalized["memory_type"] in {"episodic", "reflection"}
        assert 0.0 <= normalized["confidence"] <= 1.0
        assert isinstance(mixed_flag, bool)

    def test_event_write_plan_and_distillation(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        assert store._distill_semantic_summary("alpha") == "alpha"
        distilled = store._distill_semantic_summary("User prefers vim because it is fast")
        assert "because" not in distilled.lower() or len(distilled) < 12

        writes = store._event_mem0_write_plan(
            {
                "type": "preference",
                "summary": "User prefers vim because previous IDE failed yesterday",
                "source": "chat",
                "entities": ["user", "vim"],
            }
        )
        assert len(writes) >= 1
        assert all(isinstance(text, str) for text, _ in writes)

    def test_sanitize_helpers(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        assert MemoryStore._looks_blob_like_summary("```python\nprint('x')\n```") is True
        assert MemoryStore._looks_blob_like_summary("User likes cats") is False

        metadata = MemoryStore._sanitize_mem0_metadata(
            {"a": "x", "b": [1, 2], "c": {"nested": True}, "d": 4}
        )
        assert metadata["a"] == "x"
        assert isinstance(metadata["b"], list)
        assert isinstance(metadata["c"], str)

        assert store._sanitize_mem0_text("", allow_archival=False) == ""
        assert store._sanitize_mem0_text("User prefers Python", allow_archival=False)

    def test_compaction_helpers(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        event = {"summary": "hello", "type": "fact", "memory_type": "semantic", "topic": "general"}
        key = store._event_compaction_key(event)
        assert len(key) == 4

        compacted = store._compact_events_for_reindex(
            [
                {"summary": "hello", "type": "fact"},
                {"summary": "hello", "type": "fact"},
                {"summary": "world", "type": "fact"},
            ]
        )
        assert len(compacted) == 2

    def test_vector_health_probe_paths(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.rollout["memory_vector_health_enabled"] = True
        store.mem0.enabled = True
        store.mem0.search = MagicMock(return_value=[])
        store._mem0_get_all_rows = MagicMock(return_value=[])
        store._vector_points_count = MagicMock(return_value=0)
        store._history_row_count = MagicMock(return_value=5)
        store.reindex_from_structured_memory = MagicMock(return_value={"ok": True})

        store._ensure_vector_health()
        metrics = store.get_metrics()
        assert metrics.get("vector_health_probe_runs", 0) >= 1


class TestMemoryStoreExtraProfileAndConflicts:
    def test_profile_meta_helpers_and_pin(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
        profile["preferences"] = ["dark mode"]
        store.write_profile(profile)

        section = store._meta_section(profile, "preferences")
        assert isinstance(section, dict)
        entry = store._meta_entry(profile, "preferences", "dark mode")
        assert isinstance(entry, dict)

        store._touch_meta_entry(entry, confidence_delta=0.2)
        assert entry["confidence"] > 0

        assert store.set_item_pin("preferences", "dark mode", pinned=True) is True
        assert store.mark_item_outdated("preferences", "dark mode") is True

    def test_conflict_lifecycle(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
        profile["preferences"] = ["Use dark mode"]
        profile["conflicts"] = [
            {
                "field": "preferences",
                "old": "Use dark mode",
                "new": "Do not use dark mode",
                "status": "needs_user",
                "old_confidence": 0.4,
                "new_confidence": 0.9,
            }
        ]
        store.write_profile(profile)

        assert store._conflict_pair("Use dark mode", "Do not use dark mode") is True
        assert store._parse_conflict_user_action("keep new") == "keep_new"
        assert store.get_next_user_conflict() is not None
        prompt = store.ask_user_for_conflict(include_already_asked=True)
        assert prompt is None or isinstance(prompt, str)

        result = store.handle_user_conflict_reply("keep new")
        assert isinstance(result, dict)

        auto = store.auto_resolve_conflicts(max_items=5)
        assert isinstance(auto, dict)

    def test_resolve_conflict_details_actions(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
        profile["preferences"] = ["a", "b"]
        profile["conflicts"] = [
            {"field": "preferences", "old": "a", "new": "b", "status": "open"}
        ]
        store.write_profile(profile)

        keep_new = store.resolve_conflict_details(0, "keep_new")
        assert isinstance(keep_new, dict)

        profile = store.read_profile()
        profile["conflicts"] = [
            {"field": "preferences", "old": "a", "new": "b", "status": "open"}
        ]
        store.write_profile(profile)
        keep_old = store.resolve_conflict_details(0, "keep_old")
        assert isinstance(keep_old, dict)

        invalid = store.resolve_conflict_details(99, "keep_new")
        assert isinstance(invalid, dict)


class TestMemoryStoreExtraRetrievalAndContext:
    def test_event_similarity_and_merge(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        left = {"summary": "User likes Python", "entities": ["user", "python"]}
        right = {"summary": "User likes Python", "entities": ["user", "python"]}
        score, overlap = store._event_similarity(left, right)
        assert score >= 0
        assert overlap >= 0

        merged = store._merge_events(
            {
                "summary": "User likes Python",
                "entities": ["user", "python"],
                "confidence": 0.5,
                "source_span": [1, 2],
            },
            {
                "summary": "User prefers Python",
                "entities": ["user", "python", "coding"],
                "confidence": 0.9,
                "source_span": [2, 5],
            },
            similarity=score,
        )
        assert "entities" in merged
        assert merged["confidence"] >= 0.5

    def test_retrieve_and_memory_context(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        _seed_events(
            store,
            [
                {
                    "type": "fact",
                    "summary": "Project uses OAuth2 authentication",
                    "entities": ["project", "oauth2"],
                    "timestamp": "2026-02-20T10:00:00+00:00",
                },
                {
                    "type": "task",
                    "summary": "Deploy service in progress",
                    "entities": ["deploy"],
                    "status": "open",
                    "timestamp": "2026-02-20T10:00:00+00:00",
                },
            ],
        )
        results = store.retrieve("oauth2", top_k=3)
        assert len(results) >= 1

        context = store.get_memory_context(query="open tasks", token_budget=500)
        assert isinstance(context, str)

    def test_retrieve_with_mem0_enabled_mocked(self, tmp_path: Path) -> None:
        store = _store(tmp_path, memory_shadow_mode=True, memory_shadow_sample_rate=1.0)
        store.mem0.enabled = True

        def _fake_search(*args: object, **kwargs: object) -> tuple[list[dict[str, object]], dict[str, int]]:
            return (
                [
                    {
                        "id": "m1",
                        "text": "User prefers concise responses",
                        "score": 0.9,
                        "metadata": {
                            "memory_type": "semantic",
                            "topic": "user_preference",
                            "timestamp": "2026-02-20T10:00:00+00:00",
                        },
                    }
                ],
                {
                    "source_vector": 1,
                    "source_get_all": 0,
                    "source_history": 0,
                    "rejected_blob_like": 0,
                },
            )

        store.mem0.search = MagicMock(side_effect=_fake_search)
        out = store.retrieve("concise responses", top_k=2)
        assert isinstance(out, list)

    def test_split_and_cap_long_term_text(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        sections = store._split_md_sections("## A\nOne\n## B\nTwo")
        assert len(sections) >= 1

        text = "## One\n" + ("word " * 1200)
        capped = store._cap_long_term_text(text, token_cap=80, query="word")
        assert len(capped) <= len(text)

        fitted = store._fit_lines_to_token_cap([f"line {i}" for i in range(100)], token_cap=15)
        assert len(fitted) <= 100

    def test_snapshot_verify_and_correction(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile = store.read_profile()
        profile["preferences"] = ["Prefer concise responses"]
        store.write_profile(profile)
        _seed_events(
            store,
            [
                {
                    "type": "fact",
                    "summary": "Very old fact",
                    "timestamp": "2020-01-01T00:00:00+00:00",
                }
            ],
        )

        snapshot = store.rebuild_memory_snapshot(write=True)
        assert isinstance(snapshot, str)

        report = store.verify_memory(stale_days=30)
        assert isinstance(report, dict)

        correction = store.apply_live_user_correction(
            "Actually, I do not prefer concise responses anymore",
            channel="cli",
            chat_id="direct",
        )
        assert isinstance(correction, dict)


class TestMemoryStoreExtraCorpusAndEvaluation:
    def test_seed_corpus_and_reindex_no_mem0(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        profile_path = tmp_path / "seed_profile.json"
        events_path = tmp_path / "seed_events.jsonl"

        profile_path.write_text(
            json.dumps(
                {
                    "preferences": ["Use vim"],
                    "stable_facts": [],
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
                    "summary": "Project is Python",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        seeded = store.seed_structured_corpus(profile_path=profile_path, events_path=events_path)
        assert isinstance(seeded, dict)

        reindexed = store.reindex_from_structured_memory()
        assert isinstance(reindexed, dict)

    def test_evaluation_and_gate_helpers(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        cases = [{"query": "oauth2", "expected": ["oauth2"]}]
        eval_report = store.evaluate_retrieval_cases(cases)
        assert isinstance(eval_report, dict)

        observability = store.get_observability_report()
        gate = store.evaluate_rollout_gates(eval_report, observability)
        assert isinstance(gate, dict)

        out_file = tmp_path / "memory_eval.json"
        saved = store.save_evaluation_report(
            eval_report, observability, output_file=str(out_file)
        )
        assert saved.exists()
