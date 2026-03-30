"""Tests for memory backend configuration."""

import pytest


def test_memory_config_defaults():
    from nanobot.config.schema import MemoryConfig

    cfg = MemoryConfig()
    assert cfg.backend == "default"


def test_memory_config_backend_can_be_set():
    from nanobot.config.schema import MemoryConfig

    cfg = MemoryConfig(backend="graphiti")
    assert cfg.backend == "graphiti"


def test_memory_config_accepts_extra_graphiti_section():
    from nanobot.config.schema import MemoryConfig

    cfg = MemoryConfig(**{"backend": "graphiti", "graphiti": {"graph_db": "kuzu", "top_k": 10}})
    assert cfg.model_extra["graphiti"] == {"graph_db": "kuzu", "top_k": 10}


def test_config_has_memory_field():
    from nanobot.config.schema import Config

    cfg = Config()
    assert cfg.memory.backend == "default"


def test_memory_backend_abc_cannot_be_instantiated_directly():
    from nanobot.agent.memory import MemoryBackend

    with pytest.raises(TypeError):
        MemoryBackend()


def test_memory_store_is_memory_backend(tmp_path):
    from nanobot.agent.memory import MemoryBackend, MemoryStore

    store = MemoryStore(tmp_path)
    assert isinstance(store, MemoryBackend)


def test_memory_store_consolidates_per_turn_is_false(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    assert store.consolidates_per_turn is False


def test_memory_store_get_tools_returns_empty_list(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    assert store.get_tools() == []


async def test_memory_store_retrieve_returns_memory_context(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(exist_ok=True)
    (memory_dir / "MEMORY.md").write_text("I like coffee")

    result = await store.retrieve("anything", "telegram:123")
    assert "I like coffee" in result


async def test_memory_store_retrieve_returns_empty_string_when_no_file(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    result = await store.retrieve("anything", "telegram:123")
    assert result == ""


async def test_memory_store_consolidate_is_noop(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    # Should not raise and should not create any files
    await store.consolidate([{"role": "user", "content": "hello"}], "telegram:123")
    assert not (tmp_path / "memory" / "MEMORY.md").exists()


async def test_consolidator_skip_llm_drops_messages_without_llm_call(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch
    from nanobot.agent.memory import MemoryConsolidator, MemoryStore
    from nanobot.agent.context import ContextBuilder
    from nanobot.session.manager import SessionManager
    from nanobot.providers.base import GenerationSettings

    provider = MagicMock()
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens = MagicMock(return_value=(50, "test"))

    ws = tmp_path / "workspace"
    ws.mkdir()
    ctx = ContextBuilder(ws)
    sessions = SessionManager(ws)

    consolidator = MemoryConsolidator(
        workspace=ws,
        provider=provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=200,
        build_messages=ctx.build_messages,
        get_tool_definitions=MagicMock(return_value=[]),
    )
    consolidator.consolidate_messages = AsyncMock(return_value=True)
    consolidator._SAFETY_BUFFER = 0

    session = sessions.get_or_create("telegram:123")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
    ]

    await consolidator.maybe_consolidate_by_tokens(session, skip_llm=True)

    # LLM consolidation must NOT have been called
    consolidator.consolidate_messages.assert_not_awaited()
    # But session must have been pruned (last_consolidated advanced)
    assert session.last_consolidated > 0


async def test_consolidator_skip_llm_false_still_calls_llm(tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from nanobot.agent.memory import MemoryConsolidator
    from nanobot.agent.context import ContextBuilder
    from nanobot.session.manager import SessionManager
    from nanobot.providers.base import GenerationSettings

    provider = MagicMock()
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens = MagicMock(return_value=(1000, "test"))

    ws = tmp_path / "workspace"
    ws.mkdir()
    ctx = ContextBuilder(ws)
    sessions = SessionManager(ws)

    consolidator = MemoryConsolidator(
        workspace=ws,
        provider=provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=200,
        build_messages=ctx.build_messages,
        get_tool_definitions=MagicMock(return_value=[]),
    )
    consolidator.consolidate_messages = AsyncMock(return_value=True)
    consolidator._SAFETY_BUFFER = 0

    session = sessions.get_or_create("telegram:123")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
    ]

    await consolidator.maybe_consolidate_by_tokens(session, skip_llm=False)

    consolidator.consolidate_messages.assert_awaited()
