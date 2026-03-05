"""Tests for hybrid memory features (events/profile/retrieval/verification)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.providers.base import LLMResponse, ToolCallRequest


class TestHybridMemoryStore:
    @pytest.mark.asyncio
    async def test_hybrid_consolidation_writes_events_profile_and_metrics(
        self, tmp_path: Path
    ) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")

        session = MagicMock()
        session.messages = [
            {
                "role": "user",
                "content": "I prefer concise responses and never use dark mode.",
                "timestamp": "2026-02-20T10:00:00+00:00",
            }
            for _ in range(60)
        ]
        session.last_consolidated = 0

        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="save_1",
                            name="save_memory",
                            arguments={
                                "history_entry": "[2026-02-20 10:00] User set response preferences.",
                                "memory_update": "# Memory\nUser prefers concise responses.",
                            },
                        )
                    ],
                ),
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="events_1",
                            name="save_events",
                            arguments={
                                "events": [
                                    {
                                        "timestamp": "2026-02-20T10:00:00+00:00",
                                        "type": "preference",
                                        "summary": "User prefers concise responses.",
                                        "entities": ["user", "response style"],
                                        "salience": 0.9,
                                        "confidence": 0.95,
                                        "ttl_days": 365,
                                    }
                                ],
                                "profile_updates": {
                                    "preferences": ["User prefers concise responses."],
                                    "stable_facts": [],
                                    "active_projects": [],
                                    "relationships": [],
                                    "constraints": ["Never use dark mode."],
                                },
                            },
                        )
                    ],
                ),
            ]
        )

        ok = await store.consolidate(
            session,
            provider,
            model="test-model",
            memory_window=50,
            memory_mode="hybrid",
            enable_contradiction_check=True,
        )

        assert ok is True
        assert store.events_file.exists()
        assert store.profile_file.exists()
        assert store.metrics_file.exists()

        events = store.read_events()
        assert len(events) == 1
        assert events[0]["type"] == "preference"

        profile = store.read_profile()
        assert "User prefers concise responses." in profile["preferences"]
        assert "Never use dark mode." in profile["constraints"]

        metrics = store.get_metrics()
        assert metrics["consolidations"] >= 1
        assert metrics["events_extracted"] >= 1

    def test_retrieve_and_verify_report(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        store.append_events(
            [
                {
                    "id": "e1",
                    "timestamp": "2026-02-20T10:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "fact",
                    "summary": "Project uses OAuth2 for API authentication.",
                    "entities": ["project", "oauth2", "api"],
                    "salience": 0.8,
                    "confidence": 0.85,
                    "source_span": [0, 2],
                    "ttl_days": 365,
                },
                {
                    "id": "e2",
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "task",
                    "summary": "Legacy migration task pending.",
                    "entities": ["migration"],
                    "salience": 0.4,
                    "confidence": 0.6,
                    "source_span": [3, 4],
                    "ttl_days": 30,
                },
            ]
        )

        profile = store.read_profile()
        profile["stable_facts"] = ["Project uses OAuth2 for API authentication."]
        store.write_profile(profile)

        retrieved = store.retrieve(
            "oauth2 api",
            top_k=2,
            recency_half_life_days=30.0,
            embedding_provider="hash",
        )
        assert len(retrieved) >= 1
        assert retrieved[0]["summary"].lower().find("oauth2") >= 0
        assert retrieved[0]["retrieval_reason"]["provider"] == "keyword"
        assert retrieved[0]["provenance"]["canonical_id"] == retrieved[0]["id"]

        report = store.verify_memory(stale_days=90)
        assert report["events"] == 2
        assert report["profile_items"] >= 1
        assert report["stale_events"] >= 1

    def test_rebuild_memory_snapshot(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        profile = store.read_profile()
        profile["preferences"] = ["Prefer concise summaries."]
        profile["stable_facts"] = ["Service is deployed in eu-west-1."]
        store.write_profile(profile)

        store.append_events(
            [
                {
                    "id": "e3",
                    "timestamp": "2026-02-21T00:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "decision",
                    "summary": "Adopt hybrid memory mode in staging.",
                    "entities": ["hybrid memory", "staging"],
                    "salience": 0.7,
                    "confidence": 0.8,
                    "source_span": [5, 6],
                    "ttl_days": None,
                }
            ]
        )

        snapshot = store.rebuild_memory_snapshot(max_events=10, write=True)
        assert "Prefer concise summaries." in snapshot
        assert "Adopt hybrid memory mode in staging." in snapshot
        assert store.memory_file.exists()

    def test_profile_conflict_tracking_updates_meta_confidence(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        profile = store.read_profile()
        profile["constraints"] = ["Use dark mode"]

        added, conflicts, touched = store._apply_profile_updates(
            profile,
            updates={
                "preferences": [],
                "stable_facts": [],
                "active_projects": [],
                "relationships": [],
                "constraints": ["Do not use dark mode"],
            },
            enable_contradiction_check=True,
        )

        assert added == 1
        assert conflicts >= 1
        assert touched >= 2
        assert len(profile.get("conflicts", [])) >= 1

        meta = profile.get("meta", {}).get("constraints", {})
        assert isinstance(meta, dict)
        assert "use dark mode" in meta
        assert "do not use dark mode" in meta
        assert meta["use dark mode"]["status"] == "conflicted"
        assert meta["do not use dark mode"]["status"] == "conflicted"

    def test_verify_memory_marks_profile_stale_and_snapshot_has_open_tasks(
        self, tmp_path: Path
    ) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        profile = store.read_profile()
        profile["stable_facts"] = ["API uses OAuth2"]
        profile["meta"]["stable_facts"] = {
            "api uses oauth2": {
                "text": "API uses OAuth2",
                "confidence": 0.8,
                "evidence_count": 2,
                "status": "active",
                "last_seen_at": "2024-01-01T00:00:00+00:00",
            }
        }
        store.write_profile(profile)

        store.append_events(
            [
                {
                    "id": "t-open",
                    "timestamp": "2026-02-21T00:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "task",
                    "summary": "Review memory retrieval weights.",
                    "entities": ["memory", "weights"],
                    "salience": 0.7,
                    "confidence": 0.8,
                    "source_span": [0, 1],
                    "ttl_days": None,
                },
                {
                    "id": "t-done",
                    "timestamp": "2026-02-22T00:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "task",
                    "summary": "Migration completed and closed.",
                    "entities": ["migration"],
                    "salience": 0.6,
                    "confidence": 0.8,
                    "source_span": [2, 3],
                    "ttl_days": None,
                },
            ]
        )

        report = store.verify_memory(stale_days=90, update_profile=True)
        assert report["stale_profile_items"] >= 1
        assert report["last_verified_at"] is not None

        updated = store.read_profile()
        stale_meta = updated["meta"]["stable_facts"]["api uses oauth2"]
        assert stale_meta["status"] == "stale"

        snapshot = store.rebuild_memory_snapshot(max_events=10, write=False)
        assert "Open Tasks & Decisions" in snapshot
        open_section = snapshot.split("## Open Tasks & Decisions", 1)[1].split(
            "## Recent Episodic Highlights", 1
        )[0]
        assert "Review memory retrieval weights." in open_section
        assert "Migration completed and closed." not in open_section

    @pytest.mark.asyncio
    async def test_observability_kpis_and_user_correction_metrics(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")

        session = MagicMock()
        session.messages = [
            {
                "role": "user",
                "content": "You are wrong, actually I prefer dark mode.",
                "timestamp": "2026-02-20T10:00:00+00:00",
            }
            for _ in range(60)
        ]
        session.last_consolidated = 0

        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="save_obs_1",
                            name="save_memory",
                            arguments={
                                "history_entry": "[2026-02-20 10:00] User corrected preference.",
                                "memory_update": "# Memory\nUser prefers dark mode.",
                            },
                        )
                    ],
                ),
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="events_obs_1",
                            name="save_events",
                            arguments={
                                "events": [
                                    {
                                        "timestamp": "2026-02-20T10:00:00+00:00",
                                        "type": "preference",
                                        "summary": "User prefers dark mode.",
                                        "entities": ["user", "dark mode"],
                                        "salience": 0.85,
                                        "confidence": 0.9,
                                        "ttl_days": 365,
                                    }
                                ],
                                "profile_updates": {
                                    "preferences": ["User prefers dark mode."],
                                    "stable_facts": [],
                                    "active_projects": [],
                                    "relationships": [],
                                    "constraints": [],
                                },
                            },
                        )
                    ],
                ),
            ]
        )

        ok = await store.consolidate(
            session,
            provider,
            model="test-model",
            memory_window=50,
            memory_mode="hybrid",
            enable_contradiction_check=True,
        )
        assert ok is True

        _ = store.get_memory_context(
            mode="hybrid",
            query="dark mode",
            retrieval_k=4,
            token_budget=700,
            recency_half_life_days=30.0,
            embedding_provider="hash",
        )

        report = store.get_observability_report()
        metrics = report["metrics"]
        kpis = report["kpis"]

        assert metrics["messages_processed"] >= 1
        assert metrics["user_messages_processed"] >= 1
        assert metrics["user_corrections"] >= 1
        assert metrics["memory_context_calls"] >= 1
        assert metrics["memory_context_tokens_total"] >= 1
        assert metrics["memory_context_tokens_max"] >= 1

        assert 0.0 <= kpis["retrieval_hit_rate"] <= 1.0
        assert kpis["user_correction_rate_per_100_user_messages"] > 0.0
        assert kpis["avg_memory_context_tokens"] > 0.0

    def test_evaluate_retrieval_cases_metrics(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        store.append_events(
            [
                {
                    "id": "ev-oauth",
                    "timestamp": "2026-02-20T10:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "fact",
                    "summary": "API uses OAuth2 authentication.",
                    "entities": ["api", "oauth2", "auth"],
                    "salience": 0.9,
                    "confidence": 0.9,
                    "source_span": [0, 1],
                    "ttl_days": 365,
                },
                {
                    "id": "ev-cache",
                    "timestamp": "2026-02-20T10:01:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "fact",
                    "summary": "Cache TTL is 60 seconds.",
                    "entities": ["cache", "ttl"],
                    "salience": 0.6,
                    "confidence": 0.8,
                    "source_span": [2, 3],
                    "ttl_days": 30,
                },
            ]
        )

        report = store.evaluate_retrieval_cases(
            [
                {
                    "query": "oauth2 auth",
                    "expected_ids": ["ev-oauth"],
                    "expected_any": ["oauth2"],
                    "top_k": 3,
                },
                {
                    "query": "cache ttl",
                    "expected_any": ["cache ttl"],
                    "top_k": 3,
                },
            ],
            default_top_k=6,
            recency_half_life_days=30.0,
            embedding_provider="hash",
        )

        assert report["cases"] == 2
        assert report["summary"]["recall_at_k"] > 0.0
        assert report["summary"]["precision_at_k"] > 0.0
        assert len(report["evaluated"]) == 2

    def test_evaluate_retrieval_cases_empty_input(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        report = store.evaluate_retrieval_cases([], default_top_k=6, embedding_provider="hash")
        assert report["cases"] == 0
        assert report["summary"]["recall_at_k"] == 0.0
        assert report["summary"]["precision_at_k"] == 0.0

    def test_save_evaluation_report_writes_json(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        evaluation = {
            "cases": 1,
            "evaluated": [{"query": "oauth2", "hits": 1}],
            "summary": {"recall_at_k": 1.0, "precision_at_k": 0.5},
        }
        observability = {
            "metrics": {"retrieval_queries": 10, "retrieval_hits": 7},
            "kpis": {"retrieval_hit_rate": 0.7},
        }

        out_path = store.save_evaluation_report(evaluation, observability)
        assert out_path.exists()
        assert out_path.name.startswith("memory_eval_")

        payload = out_path.read_text(encoding="utf-8")
        assert '"evaluation"' in payload
        assert '"observability"' in payload

    def test_pin_unpin_and_mark_outdated_controls(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        profile = store.read_profile()
        profile["stable_facts"] = ["API uses OAuth2"]
        store.write_profile(profile)

        assert store.set_item_pin("stable_facts", "API uses OAuth2", pinned=True) is True
        pinned_profile = store.read_profile()
        meta = pinned_profile["meta"]["stable_facts"]["api uses oauth2"]
        assert meta["pinned"] is True

        snapshot = store.rebuild_memory_snapshot(write=False)
        assert "API uses OAuth2" in snapshot
        assert "📌" in snapshot

        assert store.set_item_pin("stable_facts", "API uses OAuth2", pinned=False) is True
        unpinned_profile = store.read_profile()
        assert unpinned_profile["meta"]["stable_facts"]["api uses oauth2"]["pinned"] is False

        assert store.mark_item_outdated("stable_facts", "API uses OAuth2") is True
        stale_profile = store.read_profile()
        assert stale_profile["meta"]["stable_facts"]["api uses oauth2"]["status"] == "stale"

    def test_conflict_list_and_resolve(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        profile = store.read_profile()
        profile["constraints"] = ["Use dark mode"]

        added, conflicts, _ = store._apply_profile_updates(
            profile,
            updates={
                "preferences": [],
                "stable_facts": [],
                "active_projects": [],
                "relationships": [],
                "constraints": ["Do not use dark mode"],
            },
            enable_contradiction_check=True,
        )
        assert added == 1
        assert conflicts >= 1
        store.write_profile(profile)

        open_conflicts = store.list_conflicts()
        assert len(open_conflicts) >= 1
        idx = int(open_conflicts[0]["index"])

        ok = store.resolve_conflict(idx, "keep_new")
        assert ok is True

        updated = store.read_profile()
        constraints = updated.get("constraints", [])
        assert "Do not use dark mode" in constraints
        assert "Use dark mode" not in constraints

        all_conflicts = store.list_conflicts(include_closed=True)
        resolved = [c for c in all_conflicts if c.get("index") == idx]
        assert resolved
        assert resolved[0]["status"] == "resolved"

    def test_live_user_correction_creates_profile_conflict_and_event(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        profile = store.read_profile()
        profile["preferences"] = ["dark mode"]
        store.write_profile(profile)

        out = store.apply_live_user_correction(
            "Correction: I now prefer light mode, not dark mode.",
            channel="cli",
            chat_id="direct",
            enable_contradiction_check=True,
        )

        assert out["applied"] >= 1
        assert out["conflicts"] >= 1
        assert out["events"] >= 1

        updated = store.read_profile()
        prefs = updated.get("preferences", [])
        assert "dark mode" in prefs
        assert "light mode" in prefs

        conflicts = updated.get("conflicts", [])
        assert conflicts
        open_conflicts = [c for c in conflicts if c.get("status") in ("open", "needs_user")]
        assert open_conflicts
        assert open_conflicts[0]["old"] == "dark mode"
        assert open_conflicts[0]["new"] == "light mode"

        events = store.read_events()
        assert events
        assert any("corrected preference" in str(e.get("summary", "")).lower() for e in events)

    def test_live_fact_correction_creates_stable_fact_conflict_and_event(
        self, tmp_path: Path
    ) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        profile = store.read_profile()
        profile["stable_facts"] = ["deployment region is eu-west-1"]
        store.write_profile(profile)

        out = store.apply_live_user_correction(
            "Correction: deployment region is us-east-1, not eu-west-1.",
            channel="cli",
            chat_id="direct",
            enable_contradiction_check=True,
        )

        assert out["applied"] >= 1
        assert out["conflicts"] >= 1
        assert out["events"] >= 1

        updated = store.read_profile()
        facts = [str(v).lower() for v in updated.get("stable_facts", [])]
        assert "deployment region is eu-west-1" in facts
        assert "deployment region is us-east-1" in facts

        conflicts = updated.get("conflicts", [])
        open_conflicts = [
            c
            for c in conflicts
            if c.get("status") in ("open", "needs_user") and c.get("field") == "stable_facts"
        ]
        assert open_conflicts
        assert str(open_conflicts[0]["old"]).lower() == "deployment region is eu-west-1"
        assert str(open_conflicts[0]["new"]).lower() == "deployment region is us-east-1"

        events = store.read_events()
        assert any("corrected fact" in str(e.get("summary", "")).lower() for e in events)

    def test_retrieval_prefers_keep_new_resolved_fact(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        events = [
            {
                "id": "region-old",
                "timestamp": "2026-02-24T17:04:00+00:00",
                "channel": "cli",
                "chat_id": "direct",
                "type": "fact",
                "summary": "Deployment region is eu-west-1.",
                "entities": ["deployment region", "eu-west-1"],
                "salience": 0.7,
                "confidence": 0.9,
                "source_span": [0, 1],
                "ttl_days": 365,
            },
            {
                "id": "region-new",
                "timestamp": "2026-02-25T02:00:00+00:00",
                "channel": "cli",
                "chat_id": "direct",
                "type": "fact",
                "summary": "Corrected deployment region: us-east-1 supersedes eu-west-1.",
                "entities": ["deployment region", "us-east-1", "eu-west-1"],
                "salience": 0.85,
                "confidence": 0.9,
                "source_span": [2, 3],
                "ttl_days": 365,
            },
        ]
        store.persistence.write_jsonl(store.events_file, events)
        store.retriever.rebuild_event_embeddings(events, embedding_provider="hash")

        profile = store.read_profile()
        profile["stable_facts"] = ["Deployment region is eu-west-1"]
        store.write_profile(profile)

        out = store.apply_live_user_correction(
            "Correction: deployment region is us-east-1, not eu-west-1.",
            channel="cli",
            chat_id="direct",
            enable_contradiction_check=True,
        )
        assert out["conflicts"] >= 1

        open_conflicts = store.list_conflicts()
        assert open_conflicts
        idx = int(open_conflicts[0]["index"])
        assert store.resolve_conflict(idx, "keep_new") is True

        retrieved = store.retrieve(
            "deployment region us-east-1 eu-west-1",
            top_k=2,
            recency_half_life_days=30.0,
            embedding_provider="hash",
        )
        assert retrieved
        assert "us-east-1" in str(retrieved[0].get("summary", "")).lower()

    def test_semantic_dedup_merges_events_and_keeps_provenance(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")

        written_1 = store.append_events(
            [
                {
                    "id": "dup-1",
                    "timestamp": "2026-02-23T10:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "fact",
                    "summary": "API uses OAuth2 authentication for requests.",
                    "entities": ["api", "oauth2"],
                    "salience": 0.75,
                    "confidence": 0.8,
                    "source_span": [0, 1],
                    "ttl_days": 365,
                }
            ]
        )
        written_2 = store.append_events(
            [
                {
                    "id": "dup-2",
                    "timestamp": "2026-02-23T11:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "fact",
                    "summary": "The API authenticates using OAuth2 tokens.",
                    "entities": ["tokens", "oauth2"],
                    "salience": 0.7,
                    "confidence": 0.78,
                    "source_span": [2, 4],
                    "ttl_days": 365,
                }
            ]
        )

        assert written_1 == 1
        assert written_2 == 0

        events = store.read_events()
        assert len(events) == 1
        event = events[0]
        assert event["canonical_id"] == "dup-1"
        assert event["merged_event_count"] >= 2
        assert len(event.get("aliases", [])) >= 2
        assert len(event.get("evidence", [])) >= 2

        retrieved = store.retrieve("oauth2 tokens", top_k=2, embedding_provider="hash")
        assert retrieved
        provenance = retrieved[0]["provenance"]
        assert provenance["canonical_id"] == "dup-1"
        assert provenance["evidence_count"] >= 2

        metrics = store.get_metrics()
        assert metrics["event_dedup_merges"] >= 1

    def test_non_duplicate_events_remain_separate(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")
        written = store.append_events(
            [
                {
                    "id": "nd-1",
                    "timestamp": "2026-02-23T10:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "fact",
                    "summary": "Primary database is PostgreSQL.",
                    "entities": ["postgresql", "database"],
                    "salience": 0.7,
                    "confidence": 0.8,
                    "source_span": [0, 1],
                    "ttl_days": 365,
                },
                {
                    "id": "nd-2",
                    "timestamp": "2026-02-23T10:05:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "fact",
                    "summary": "Deployment region is eu-west-1.",
                    "entities": ["region", "eu-west-1"],
                    "salience": 0.7,
                    "confidence": 0.8,
                    "source_span": [2, 3],
                    "ttl_days": 365,
                },
            ]
        )

        assert written == 2
        events = store.read_events()
        assert len(events) == 2
        ids = {str(e.get("id")) for e in events}
        assert {"nd-1", "nd-2"}.issubset(ids)

    def test_local_keyword_retrieval_without_mem0(self, tmp_path: Path) -> None:
        """When mem0 is unavailable, retrieve() uses local keyword matching."""
        store = MemoryStore(tmp_path, embedding_provider="hash", vector_backend="sqlite")
        store.append_events(
            [
                {
                    "id": "sql-ev-1",
                    "timestamp": "2026-02-23T00:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "fact",
                    "summary": "Primary database is PostgreSQL.",
                    "entities": ["database", "postgresql"],
                    "salience": 0.8,
                    "confidence": 0.8,
                    "source_span": [0, 1],
                    "ttl_days": 365,
                }
            ]
        )

        retrieved = store.retrieve("postgresql database", top_k=2, embedding_provider="hash")
        assert retrieved
        assert retrieved[0]["retrieval_reason"]["provider"] == "keyword"
        assert retrieved[0]["retrieval_reason"]["backend"] == "jsonl"

    def test_keyword_retrieval_with_recency(self, tmp_path: Path) -> None:
        """Recency weighting should boost recent events over old ones."""
        store = MemoryStore(tmp_path, embedding_provider="hash", vector_backend="faiss")
        store.append_events(
            [
                {
                    "id": "old-ev",
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "fact",
                    "summary": "Primary database runs on PostgreSQL in eu-west-1.",
                    "entities": ["database", "postgresql", "eu-west-1"],
                    "salience": 0.7,
                    "confidence": 0.8,
                    "source_span": [2, 3],
                    "ttl_days": 365,
                },
                {
                    "id": "new-ev",
                    "timestamp": "2026-03-01T00:00:00+00:00",
                    "channel": "cli",
                    "chat_id": "direct",
                    "type": "decision",
                    "summary": "Decided to migrate the database cluster to eu-west-1.",
                    "entities": ["migration", "database", "eu-west-1"],
                    "salience": 0.7,
                    "confidence": 0.8,
                    "source_span": [4, 5],
                    "ttl_days": 365,
                },
            ]
        )

        retrieved = store.retrieve(
            "database eu-west-1",
            top_k=2,
            recency_half_life_days=30.0,
            embedding_provider="hash",
        )
        assert len(retrieved) == 2
        # The more recent event should rank first due to recency boost
        assert retrieved[0]["id"] == "new-ev"
