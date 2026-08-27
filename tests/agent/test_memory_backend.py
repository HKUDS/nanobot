"""Tests for the file-backed pluggable memory boundary."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryArchiver, MemoryStore
from nanobot.agent.memory_backend import MemoryBackend
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse
from nanobot.utils.llm_runtime import LLMRuntime


def test_memory_store_implements_backend_and_recalls_durable_sources(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.write_memory("# Projects\n\nProject Apollo uses Rust for telemetry.")
    store.ingest(
        "Apollo launch review moved to Friday.",
        session_key="cli:apollo",
    )

    records = store.recall("Apollo", limit=5)

    assert isinstance(store, MemoryBackend)
    assert [record.source for record in records] == [
        "memory/MEMORY.md",
        "memory/history.jsonl",
    ]
    assert records[0].id == "memory:2"
    assert records[1].id == "history:1"
    assert records[1].session_key == "cli:apollo"
    assert records[1].timestamp is not None


def test_memory_store_recall_is_ranked_limited_and_bounded(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.ingest("release alpha " + "x" * 2_000, session_key="cli:old")
    store.ingest("release beta", session_key="cli:new")
    store.ingest("unrelated note", session_key="cli:other")

    records = store.recall("release", limit=1)

    assert len(records) == 1
    assert records[0].id == "history:2"
    assert len(records[0].content) <= store._RECALL_CONTENT_CHARS + 2


def test_memory_store_recall_matches_query_terms_without_exact_phrase(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.ingest("The project uses a Friday deadline.")

    records = store.recall("project deadline", limit=5)

    assert [record.id for record in records] == ["history:1"]


def test_memory_store_recall_skips_corrupt_and_malformed_history(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.history_file.write_bytes(
        b"\xff\n"
        b'{"cursor":"bad","timestamp":"2026-01-01","content":"needle bad"}\n'
        b'{"cursor":2,"timestamp":7,"content":"needle malformed"}\n'
        b'{"cursor":3,"timestamp":"2026-01-03","content":"needle valid"}\n'
    )

    records = store.recall("needle", limit=5)

    assert [record.id for record in records] == ["history:3"]


def test_memory_store_recall_empty_query_or_limit_returns_nothing(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.ingest("anything")

    assert store.recall("   ", limit=5) == []
    assert store.recall("anything", limit=0) == []


@pytest.mark.asyncio
async def test_memory_archiver_ingests_through_configured_backend(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    backend = MagicMock(spec=MemoryBackend)
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings(max_tokens=100)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="durable summary"))
    runtime = LLMRuntime.capture(
        provider,
        "test-model",
        context_window_tokens=16_000,
    )
    archiver = MemoryArchiver(
        store=store,
        backend=backend,
        build_messages=MagicMock(),
        get_tool_definitions=MagicMock(return_value=[]),
    )

    result = await archiver.archive(
        [{"role": "user", "content": "remember this"}],
        runtime=runtime,
        session_key="cli:test",
        request_messages=[{"role": "user", "content": "summarize"}],
        request_tools=[],
    )

    assert result == "durable summary"
    backend.ingest.assert_called_once_with(
        "durable summary",
        max_chars=64_000,
        session_key="cli:test",
    )
    assert store.read_unprocessed_history(0) == []
