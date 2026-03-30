"""Tests for GraphitiMemoryBackend and GraphitiConfig."""

import pytest


# ── Config ──────────────────────────────────────────────────────────────────

def test_graphiti_config_defaults():
    from nanobot_graphiti.config import GraphitiConfig

    cfg = GraphitiConfig()
    assert cfg.graph_db == "kuzu"
    assert cfg.kuzu_path == "~/.nanobot/workspace/memory/graph"
    assert cfg.top_k == 5
    assert cfg.scope == "user"
    assert cfg.embedding_model == "text-embedding-3-small"


def test_graphiti_config_accepts_neo4j():
    from nanobot_graphiti.config import GraphitiConfig

    cfg = GraphitiConfig(graph_db="neo4j", neo4j_uri="bolt://myhost:7687", neo4j_password="secret")
    assert cfg.graph_db == "neo4j"
    assert cfg.neo4j_uri == "bolt://myhost:7687"


def test_graphiti_config_from_nanobot_config_kuzu():
    """_from_nanobot_config() parses memory.model_extra["graphiti"] section."""
    from unittest.mock import MagicMock
    from nanobot_graphiti.config import GraphitiConfig

    nanobot_config = MagicMock()
    nanobot_config.memory.model_extra = {"graphiti": {"graph_db": "kuzu", "top_k": 10}}

    cfg = GraphitiConfig._from_nanobot_config(nanobot_config)
    assert cfg.graph_db == "kuzu"
    assert cfg.top_k == 10


def test_graphiti_config_from_nanobot_config_missing_section():
    """_from_nanobot_config() falls back to defaults when section absent."""
    from unittest.mock import MagicMock
    from nanobot_graphiti.config import GraphitiConfig

    nanobot_config = MagicMock()
    nanobot_config.memory.model_extra = {}

    cfg = GraphitiConfig._from_nanobot_config(nanobot_config)
    assert cfg.graph_db == "kuzu"
    assert cfg.top_k == 5


# ── Backend contract ─────────────────────────────────────────────────────────

def test_graphiti_backend_is_memory_backend():
    from nanobot.agent.memory import MemoryBackend
    from nanobot_graphiti.backend import GraphitiMemoryBackend

    assert issubclass(GraphitiMemoryBackend, MemoryBackend)


def test_graphiti_backend_consolidates_per_turn_is_true():
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig())
    assert backend.consolidates_per_turn is True


async def test_graphiti_backend_start_calls_build_indices(mock_graphiti, mock_provider):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    mock_graphiti.build_indices_and_constraints.assert_awaited_once()


async def test_graphiti_backend_stop_closes_client(mock_graphiti, mock_provider):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)
    await backend.stop()

    mock_graphiti.close.assert_awaited_once()


async def test_graphiti_backend_stop_is_safe_before_start():
    """stop() before start() must not raise."""
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig())
    await backend.stop()  # no exception


# ── consolidate() ────────────────────────────────────────────────────────────

async def test_consolidate_calls_add_episode(mock_graphiti, mock_provider, session_key):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    await backend.consolidate(messages, session_key)

    mock_graphiti.add_episode.assert_awaited_once()
    call_kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert call_kwargs["group_id"] == "123456"   # scope="user" strips "telegram:"
    assert "Hello" in call_kwargs["episode_body"]
    assert "Hi there!" in call_kwargs["episode_body"]


async def test_consolidate_uses_session_scope(mock_graphiti, mock_provider):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(
        GraphitiConfig(scope="session"),
        _graphiti_factory=lambda **kw: mock_graphiti,
    )
    await backend.start(mock_provider)
    await backend.consolidate([{"role": "user", "content": "hi"}], "telegram:123456")

    call_kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert call_kwargs["group_id"] == "telegram:123456"


async def test_consolidate_swallows_errors(mock_graphiti, mock_provider, session_key):
    """consolidate() must not raise even if graphiti.add_episode() fails."""
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    mock_graphiti.add_episode.side_effect = RuntimeError("graph unavailable")

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)
    await backend.consolidate([{"role": "user", "content": "hi"}], session_key)
    # No exception raised — test passes if we reach here


async def test_consolidate_skips_empty_messages(mock_graphiti, mock_provider, session_key):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)
    await backend.consolidate([], session_key)

    mock_graphiti.add_episode.assert_not_awaited()


# ── retrieve() ───────────────────────────────────────────────────────────────

async def test_retrieve_calls_search_with_group_id(mock_graphiti, mock_provider, session_key):
    from unittest.mock import MagicMock
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    edge = MagicMock()
    edge.fact = "User likes coffee"
    edge.uuid = "abc-123"
    mock_graphiti.search.return_value = [edge]

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    result = await backend.retrieve("coffee", session_key, top_k=3)

    mock_graphiti.search.assert_awaited_once_with("coffee", group_ids=["123456"], num_results=3)
    assert "User likes coffee" in result
    assert "[Memory" in result


async def test_retrieve_returns_empty_string_when_no_results(mock_graphiti, mock_provider, session_key):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    mock_graphiti.search.return_value = []

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    result = await backend.retrieve("anything", session_key)
    assert result == ""


async def test_retrieve_formats_multiple_facts(mock_graphiti, mock_provider, session_key):
    from unittest.mock import MagicMock
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    edges = []
    for i, fact in enumerate(["Likes coffee", "Works in Berlin", "Has a cat"]):
        edge = MagicMock()
        edge.fact = fact
        edge.uuid = f"uuid-{i}"
        edges.append(edge)
    mock_graphiti.search.return_value = edges

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    result = await backend.retrieve("tell me about user", session_key)
    assert "Likes coffee" in result
    assert "Works in Berlin" in result
    assert "Has a cat" in result
    assert "[Memory — 3 relevant facts]" in result
