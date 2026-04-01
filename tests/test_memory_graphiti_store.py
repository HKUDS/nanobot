"""Unit tests for GraphitiMemoryStore (graphiti-core adapter)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.memory.base import BaseMemoryStore


def _make_messages(count: int = 3) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(count)
    ]


def _make_edge(uuid: str = "e1", fact: str = "user likes cats"):
    return SimpleNamespace(
        uuid=uuid,
        fact=fact,
        valid_at="2026-01-01",
        invalid_at="",
    )


def _mock_graphiti_class():
    """Create a mock Graphiti class that returns an async-ready instance."""
    mock_instance = MagicMock()
    mock_instance.build_indices_and_constraints = AsyncMock()
    mock_instance.add_episode = AsyncMock(return_value={"episode_id": "ep1"})
    mock_instance.search = AsyncMock(return_value=[_make_edge()])
    mock_instance.delete_episode = AsyncMock()

    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls, mock_instance


@pytest.fixture
def graphiti_store(tmp_path: Path):
    """Create a GraphitiMemoryStore with mocked graphiti-core backend."""
    mock_cls, mock_inst = _mock_graphiti_class()
    with (
        patch("nanobot.agent.memory.graphiti_store._lazy_import_graphiti", return_value=mock_cls),
        patch("nanobot.agent.memory.graphiti_store._resolve_graph_db", return_value={"uri": "bolt://mock:7687"}),
        patch("nanobot.agent.memory.graphiti_store._build_llm_client", return_value=MagicMock()),
        patch("nanobot.agent.memory.graphiti_store._build_embedder", return_value=MagicMock()),
        patch("nanobot.agent.memory.graphiti_store._build_cross_encoder", return_value=MagicMock()),
    ):
        from nanobot.agent.memory.graphiti_store import GraphitiMemoryStore

        store = GraphitiMemoryStore(
            tmp_path,
            graph_db={"falkordb": {"enable": True, "host": "mock", "port": 6380}},
            llm={"model": "gpt-4.1-mini", "api_key": "sk-x"},
            embedder={"model": "text-embedding-3-small", "api_key": "sk-x"},
            cross_encoder={"model": "gpt-4.1-nano", "api_key": "sk-x"},
        )
    store._graphiti = mock_inst
    store._initialized = True
    store._mock_instance = mock_inst
    store._mock_cls = mock_cls
    return store


# ── Init ──────────────────────────────────────────────────────────────────────


class TestGraphitiStoreInit:

    def test_is_subclass_of_base(self, graphiti_store):
        assert isinstance(graphiti_store, BaseMemoryStore)

    def test_import_error_without_library(self):
        from nanobot.agent.memory.graphiti_store import _lazy_import_graphiti

        with patch.dict("sys.modules", {"graphiti_core": None}):
            with pytest.raises(ImportError, match="graphiti-core"):
                _lazy_import_graphiti()

    def test_dedicated_loop_is_running(self, graphiti_store):
        assert graphiti_store._dedicated_loop.is_running()
        assert graphiti_store._dedicated_thread.is_alive()

    def test_init_stores_config(self, tmp_path: Path):
        mock_cls, _ = _mock_graphiti_class()
        with patch("nanobot.agent.memory.graphiti_store._lazy_import_graphiti", return_value=mock_cls):
            from nanobot.agent.memory.graphiti_store import GraphitiMemoryStore

            store = GraphitiMemoryStore(
                tmp_path,
                graph_db={"neo4j": {"enable": True, "url": "bolt://neo4j:7687"}},
                llm={"model": "gpt-4.1-mini"},
            )
        assert store._graph_db_cfg == {"neo4j": {"enable": True, "url": "bolt://neo4j:7687"}}
        assert store._llm_cfg == {"model": "gpt-4.1-mini"}
        assert store._graphiti is None


# ── Messages to episode body ──────────────────────────────────────────────────


class TestMessagesToEpisodeBody:

    def test_basic_conversion(self, graphiti_store):
        body = graphiti_store._messages_to_episode_body(_make_messages(3))
        assert "User: msg 0" in body
        assert "Assistant: msg 1" in body
        assert "User: msg 2" in body

    def test_filters_tool_messages(self, graphiti_store):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "response"},
        ]
        body = graphiti_store._messages_to_episode_body(messages)
        assert "tool result" not in body
        assert "hello" in body
        assert "response" in body

    def test_filters_empty_content(self, graphiti_store):
        messages = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "valid"},
        ]
        body = graphiti_store._messages_to_episode_body(messages)
        assert body == "User: valid"

    def test_filters_non_string_content(self, graphiti_store):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "multimodal"}]},
            {"role": "user", "content": "plain text"},
        ]
        body = graphiti_store._messages_to_episode_body(messages)
        assert body == "User: plain text"

    def test_empty_messages_returns_empty(self, graphiti_store):
        assert graphiti_store._messages_to_episode_body([]) == ""


# ── Edge to dict ──────────────────────────────────────────────────────────────


class TestEdgeToDict:

    def test_converts_edge_namespace(self, graphiti_store):
        edge = _make_edge("abc-123", "user is an engineer")
        d = graphiti_store._edge_to_dict(edge)
        assert d["id"] == "abc-123"
        assert d["memory"] == "user is an engineer"
        assert "valid_at" in d
        assert "invalid_at" in d

    def test_missing_fields_use_defaults(self, graphiti_store):
        edge = SimpleNamespace()
        d = graphiti_store._edge_to_dict(edge)
        assert d["id"] == ""
        assert isinstance(d["memory"], str)


# ── CRUD ──────────────────────────────────────────────────────────────────────


class TestGraphitiStoreCRUD:

    @pytest.mark.asyncio
    async def test_add_delegates_to_graphiti(self, graphiti_store):
        result = await graphiti_store.add(_make_messages(2), user_id="alice")
        graphiti_store._mock_instance.add_episode.assert_called_once()
        call_kwargs = graphiti_store._mock_instance.add_episode.call_args[1]
        assert call_kwargs["group_id"] == "alice"
        assert "episode_body" in call_kwargs
        assert result == {"episode_id": "ep1"}

    @pytest.mark.asyncio
    async def test_add_empty_body_returns_empty_dict(self, graphiti_store):
        messages = [{"role": "tool", "content": "only tool messages"}]
        result = await graphiti_store.add(messages, user_id="alice")
        assert result == {}
        graphiti_store._mock_instance.add_episode.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_failure_raises(self, graphiti_store):
        graphiti_store._mock_instance.add_episode.side_effect = RuntimeError("graph error")
        with pytest.raises(RuntimeError, match="graph error"):
            await graphiti_store.add(_make_messages(), user_id="alice")

    @pytest.mark.asyncio
    async def test_search_returns_dicts(self, graphiti_store):
        graphiti_store._mock_instance.search = AsyncMock(return_value=[
            _make_edge("e1", "fact 1"),
            _make_edge("e2", "fact 2"),
        ])
        results = await graphiti_store.search("test query", user_id="alice", limit=3)
        assert len(results) == 2
        assert results[0]["memory"] == "fact 1"
        assert results[1]["id"] == "e2"
        graphiti_store._mock_instance.search.assert_called_once_with(
            query="test query", group_ids=["alice"], num_results=3
        )

    @pytest.mark.asyncio
    async def test_search_failure_returns_empty_list(self, graphiti_store):
        graphiti_store._mock_instance.search = AsyncMock(side_effect=RuntimeError("fail"))
        results = await graphiti_store.search("query")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_all_calls_search_with_wildcard(self, graphiti_store):
        graphiti_store._mock_instance.search = AsyncMock(return_value=[_make_edge()])
        results = await graphiti_store.get_all(user_id="bob", limit=20)
        assert len(results) == 1
        graphiti_store._mock_instance.search.assert_called_once_with(
            query="*", group_ids=["bob"], num_results=20
        )

    @pytest.mark.asyncio
    async def test_update_returns_false(self, graphiti_store):
        result = await graphiti_store.update("m1", "new content")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_success(self, graphiti_store):
        result = await graphiti_store.delete("ep1")
        assert result is True
        graphiti_store._mock_instance.delete_episode.assert_called_once_with("ep1")

    @pytest.mark.asyncio
    async def test_delete_failure_returns_false(self, graphiti_store):
        graphiti_store._mock_instance.delete_episode = AsyncMock(
            side_effect=RuntimeError("not found")
        )
        result = await graphiti_store.delete("ep1")
        assert result is False


# ── Memory context ────────────────────────────────────────────────────────────


class TestGraphitiStoreContext:

    def test_get_memory_context_with_facts(self, graphiti_store):
        graphiti_store._mock_instance.search = AsyncMock(return_value=[
            _make_edge("e1", "user likes cats"),
            _make_edge("e2", "user is a developer"),
        ])
        ctx = graphiti_store.get_memory_context(query="user info", user_id="alice")
        assert "Graphiti Knowledge Graph" in ctx
        assert "user likes cats" in ctx
        assert "user is a developer" in ctx

    def test_get_memory_context_empty(self, graphiti_store):
        graphiti_store._mock_instance.search = AsyncMock(return_value=[])
        assert graphiti_store.get_memory_context() == ""

    def test_get_memory_context_exception_returns_empty(self, graphiti_store):
        graphiti_store._mock_instance.search = AsyncMock(side_effect=RuntimeError("fail"))
        assert graphiti_store.get_memory_context() == ""


# ── Consolidation ─────────────────────────────────────────────────────────────


class TestGraphitiStoreConsolidation:

    @pytest.mark.asyncio
    async def test_consolidate_empty_returns_true(self, graphiti_store):
        provider = AsyncMock()
        result = await graphiti_store.consolidate([], provider, "model")
        assert result is True

    @pytest.mark.asyncio
    async def test_consolidate_delegates_to_add(self, graphiti_store):
        provider = AsyncMock()
        messages = _make_messages(3)
        result = await graphiti_store.consolidate(messages, provider, "model", user_id="alice")
        assert result is True
        graphiti_store._mock_instance.add_episode.assert_called_once()
        call_kwargs = graphiti_store._mock_instance.add_episode.call_args[1]
        assert call_kwargs["group_id"] == "alice"
        assert graphiti_store._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_consolidate_failure_increments_counter(self, graphiti_store):
        provider = AsyncMock()
        graphiti_store._mock_instance.add_episode.side_effect = RuntimeError("fail")
        result = await graphiti_store.consolidate(_make_messages(), provider, "m")
        assert result is False
        assert graphiti_store._consecutive_failures == 1


# ── Helpers ───────────────────────────────────────────────────────────────────


class TestGraphitiHelpers:

    def test_camel_to_snake(self):
        from nanobot.agent.memory.graphiti_store import _camel_to_snake

        assert _camel_to_snake("apiKey") == "api_key"
        assert _camel_to_snake("baseUrl") == "base_url"
        assert _camel_to_snake("HTTPSProxy") == "https_proxy"
        assert _camel_to_snake("already_snake") == "already_snake"

    def test_normalize_keys(self):
        from nanobot.agent.memory.graphiti_store import _normalize_keys

        d = {"apiKey": "sk-x", "baseUrl": "http://x", "nested": {"innerKey": "val"}}
        result = _normalize_keys(d)
        assert result == {"api_key": "sk-x", "base_url": "http://x", "nested": {"inner_key": "val"}}
