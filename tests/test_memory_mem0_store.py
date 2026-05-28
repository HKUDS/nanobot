"""Unit tests for Mem0MemoryStore (mem0ai adapter)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.memory.base import BaseMemoryStore


def _make_messages(count: int = 3) -> list[dict]:
    return [
        {"role": "user", "content": f"msg {i}", "timestamp": "2026-03-22 10:00"}
        for i in range(count)
    ]


def _mock_mem0_module():
    """Create a mock mem0 Memory class for testing without the real library."""
    mock_memory_instance = MagicMock()
    mock_memory_instance.add.return_value = {
        "results": [{"id": "m1", "memory": "extracted fact"}]
    }
    mock_memory_instance.search.return_value = {
        "results": [{"id": "m1", "memory": "user likes cats"}]
    }
    mock_memory_instance.get_all.return_value = {
        "results": [
            {"id": "m1", "memory": "user likes cats"},
            {"id": "m2", "memory": "user is a developer"},
        ]
    }
    mock_memory_instance.update.return_value = None
    mock_memory_instance.delete.return_value = None

    mock_memory_cls = MagicMock()
    mock_memory_cls.return_value = mock_memory_instance
    mock_memory_cls.from_config.return_value = mock_memory_instance
    return mock_memory_cls, mock_memory_instance


@pytest.fixture
def mem0_store(tmp_path: Path):
    """Create a Mem0MemoryStore with a mocked mem0 backend."""
    mock_cls, mock_inst = _mock_mem0_module()
    with patch("nanobot.agent.memory.mem0_store._lazy_import_mem0", return_value=mock_cls):
        from nanobot.agent.memory.mem0_store import Mem0MemoryStore
        store = Mem0MemoryStore(tmp_path)
    store._mock_instance = mock_inst
    return store


class TestMem0MemoryStoreInit:

    def test_is_subclass_of_base(self, mem0_store):
        assert isinstance(mem0_store, BaseMemoryStore)

    def test_import_error_without_library(self, tmp_path: Path):
        from nanobot.agent.memory.mem0_store import _lazy_import_mem0
        with patch.dict("sys.modules", {"mem0": None}):
            with pytest.raises(ImportError, match="mem0ai"):
                _lazy_import_mem0()

    def test_init_with_config(self, tmp_path: Path):
        mock_cls, _ = _mock_mem0_module()
        raw = {"llm": {"provider": "openai", "config": {"model": "gpt-4o-mini", "apiKey": "sk-x", "apiBase": "http://example.com"}}}
        with patch("nanobot.agent.memory.mem0_store._lazy_import_mem0", return_value=mock_cls):
            from nanobot.agent.memory.mem0_store import Mem0MemoryStore
            Mem0MemoryStore(tmp_path, config=raw)
        # from_config must be called once with normalised (snake_case + openai_base_url) keys
        mock_cls.from_config.assert_called_once()
        passed = mock_cls.from_config.call_args[0][0]
        assert passed["llm"]["config"]["api_key"] == "sk-x"
        assert passed["llm"]["config"]["openai_base_url"] == "http://example.com"
        # embedder auto-derived when missing
        assert "embedder" in passed

    def test_init_without_config_defers_instantiation(self, tmp_path: Path):
        """Without an llm config, Memory() must NOT be called at construction time."""
        mock_cls, _ = _mock_mem0_module()
        with patch("nanobot.agent.memory.mem0_store._lazy_import_mem0", return_value=mock_cls):
            from nanobot.agent.memory.mem0_store import Mem0MemoryStore
            store = Mem0MemoryStore(tmp_path)
        mock_cls.assert_not_called()
        mock_cls.from_config.assert_not_called()
        assert store._mem0 is None


class TestMem0MemoryStoreCRUD:

    @pytest.mark.asyncio
    async def test_add_delegates_to_mem0(self, mem0_store):
        messages = _make_messages(2)
        result = await mem0_store.add(messages, user_id="alice")
        mem0_store._mock_instance.add.assert_called_once_with(
            messages, user_id="alice"
        )
        assert isinstance(result, dict)
        assert "results" in result

    @pytest.mark.asyncio
    async def test_search_delegates_to_mem0(self, mem0_store):
        results = await mem0_store.search("cats", user_id="alice", limit=3)
        mem0_store._mock_instance.search.assert_called_once_with(
            query="cats", user_id="alice", limit=3
        )
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["memory"] == "user likes cats"

    @pytest.mark.asyncio
    async def test_search_handles_non_dict_result(self, mem0_store):
        mem0_store._mock_instance.search.return_value = [
            {"id": "x", "memory": "raw result"}
        ]
        results = await mem0_store.search("test")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_get_all_delegates_to_mem0(self, mem0_store):
        results = await mem0_store.get_all(user_id="bob")
        mem0_store._mock_instance.get_all.assert_called_once_with(user_id="bob")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_update_success(self, mem0_store):
        result = await mem0_store.update("m1", "updated content")
        assert result is True
        mem0_store._mock_instance.update.assert_called_once_with("m1", "updated content")

    @pytest.mark.asyncio
    async def test_update_failure_returns_false(self, mem0_store):
        mem0_store._mock_instance.update.side_effect = RuntimeError("DB error")
        result = await mem0_store.update("m1", "fail")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_success(self, mem0_store):
        result = await mem0_store.delete("m1")
        assert result is True
        mem0_store._mock_instance.delete.assert_called_once_with("m1")

    @pytest.mark.asyncio
    async def test_delete_failure_returns_false(self, mem0_store):
        mem0_store._mock_instance.delete.side_effect = RuntimeError("not found")
        result = await mem0_store.delete("m1")
        assert result is False


class TestMem0MemoryStoreContext:

    def test_get_memory_context_with_memories(self, mem0_store):
        ctx = mem0_store.get_memory_context()
        assert "## Long-term Memory (Mem0)" in ctx
        assert "user likes cats" in ctx
        assert "user is a developer" in ctx

    def test_get_memory_context_empty(self, mem0_store):
        mem0_store._mock_instance.get_all.return_value = {"results": []}
        assert mem0_store.get_memory_context() == ""

    def test_get_memory_context_exception_returns_empty(self, mem0_store):
        mem0_store._mock_instance.get_all.side_effect = RuntimeError("fail")
        assert mem0_store.get_memory_context() == ""

    def test_get_memory_context_respects_user_id(self, mem0_store):
        mem0_store.get_memory_context(user_id="alice")
        mem0_store._mock_instance.get_all.assert_called_with(user_id="alice")


class TestMem0MemoryStoreConsolidation:

    @pytest.mark.asyncio
    async def test_consolidate_empty_returns_true(self, mem0_store):
        provider = AsyncMock()
        result = await mem0_store.consolidate([], provider, "model")
        assert result is True

    @pytest.mark.asyncio
    async def test_consolidate_feeds_to_add(self, mem0_store):
        provider = AsyncMock()
        messages = _make_messages(3)
        result = await mem0_store.consolidate(messages, provider, "model")
        assert result is True
        assert mem0_store._mock_instance.add.called
        assert mem0_store._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_consolidate_skips_empty_content(self, mem0_store):
        provider = AsyncMock()
        messages = [{"role": "user", "content": ""}, {"role": "user", "content": "valid"}]
        await mem0_store.consolidate(messages, provider, "model")
        call_args = mem0_store._mock_instance.add.call_args
        passed_messages = call_args[0][0]
        assert all(m["content"] for m in passed_messages)

    @pytest.mark.asyncio
    async def test_consolidate_failure_increments_counter(self, mem0_store):
        provider = AsyncMock()
        mem0_store._mock_instance.add.side_effect = RuntimeError("fail")
        result = await mem0_store.consolidate(_make_messages(), provider, "m")
        assert result is False
        assert mem0_store._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_consolidate_builds_config_from_provider_when_no_llm_config(
        self, tmp_path: Path
    ):
        """When no llm config was given, consolidate() must build one from provider."""
        mock_cls, mock_inst = _mock_mem0_module()
        with patch("nanobot.agent.memory.mem0_store._lazy_import_mem0", return_value=mock_cls):
            from nanobot.agent.memory.mem0_store import Mem0MemoryStore
            store = Mem0MemoryStore(tmp_path)  # no config

        provider = MagicMock()
        provider.api_key = "sk-test-key"
        provider.api_base = "https://api.example.com/v1"

        messages = [{"role": "user", "content": "test message"}]
        result = await store.consolidate(messages, provider, "gpt-4o-mini")

        assert result is True
        # Memory.from_config should have been called (not Memory())
        mock_cls.assert_not_called()
        mock_cls.from_config.assert_called_once()
        built_cfg = mock_cls.from_config.call_args[0][0]
        assert "llm" in built_cfg
        assert built_cfg["llm"]["config"]["model"] == "gpt-4o-mini"
        assert built_cfg["llm"]["config"]["api_key"] == "sk-test-key"
        assert built_cfg["llm"]["config"]["openai_base_url"] == "https://api.example.com/v1"
        assert "embedder" in built_cfg

    @pytest.mark.asyncio
    async def test_ensure_initialized_not_called_twice(self, tmp_path: Path):
        """_mem0 must be initialized exactly once even across multiple method calls."""
        mock_cls, mock_inst = _mock_mem0_module()
        with patch("nanobot.agent.memory.mem0_store._lazy_import_mem0", return_value=mock_cls):
            from nanobot.agent.memory.mem0_store import Mem0MemoryStore
            store = Mem0MemoryStore(tmp_path, config={"llm": {"provider": "openai"}})

        # Already initialized at __init__; subsequent calls must not re-init.
        assert store._mem0 is mock_inst
        mock_cls.from_config.reset_mock()

        await store.add(_make_messages())
        mock_cls.from_config.assert_not_called()  # no second init
