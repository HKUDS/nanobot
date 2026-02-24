"""Tests for hybrid memory features (events/profile/retrieval/verification)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.providers.base import LLMResponse, ToolCallRequest


class TestHybridMemoryStore:
    @pytest.mark.asyncio
    async def test_hybrid_consolidation_writes_events_profile_and_metrics(self, tmp_path: Path) -> None:
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

        index_file = store.index_dir / "vectors_hash.json"
        assert index_file.exists()

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
        assert retrieved[0]["retrieval_reason"]["provider"] == "hash"

        index_file = store.index_dir / "vectors_hash.json"
        assert index_file.exists()

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

    def test_verify_memory_marks_profile_stale_and_snapshot_has_open_tasks(self, tmp_path: Path) -> None:
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
        open_section = snapshot.split("## Open Tasks & Decisions", 1)[1].split("## Recent Episodic Highlights", 1)[0]
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
