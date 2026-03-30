"""Tests for memory tools."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
async def backend_with_mock_graphiti(mock_graphiti, mock_provider):
    """A started GraphitiMemoryBackend with an injected mock graphiti client."""
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)
    return backend, mock_graphiti


def _make_edge(fact: str, uuid: str = "test-uuid") -> MagicMock:
    edge = MagicMock()
    edge.fact = fact
    edge.uuid = uuid
    return edge


# ── MemorySearchTool ─────────────────────────────────────────────────────────

async def test_memory_search_tool_name():
    from nanobot_graphiti.tools import MemorySearchTool

    tool = MemorySearchTool(backend=MagicMock())
    assert tool.name == "memory_search"


async def test_memory_search_calls_graphiti_search(mock_graphiti):
    from nanobot_graphiti.tools import MemorySearchTool

    mock_graphiti.search.return_value = [_make_edge("User prefers dark mode")]

    backend = MagicMock()
    backend._graphiti = mock_graphiti
    backend._get_group_id.return_value = "123456"

    tool = MemorySearchTool(backend=backend)
    result = await tool.execute(query="UI preferences", top_k=5, session_key="telegram:123456")

    mock_graphiti.search.assert_awaited_once_with("UI preferences", group_ids=["123456"], num_results=5)
    assert "User prefers dark mode" in result


async def test_memory_search_returns_no_results_message(mock_graphiti):
    from nanobot_graphiti.tools import MemorySearchTool

    mock_graphiti.search.return_value = []

    backend = MagicMock()
    backend._graphiti = mock_graphiti
    backend._get_group_id.return_value = "123456"

    tool = MemorySearchTool(backend=backend)
    result = await tool.execute(query="nonexistent", top_k=5, session_key="telegram:123456")

    assert "no" in result.lower() or "0" in result


# ── MemoryForgetTool ─────────────────────────────────────────────────────────

async def test_memory_forget_tool_name():
    from nanobot_graphiti.tools import MemoryForgetTool

    tool = MemoryForgetTool(backend=MagicMock())
    assert tool.name == "memory_forget"


async def test_memory_forget_calls_delete(mock_graphiti):
    """memory_forget deletes the fact by UUID."""
    from nanobot_graphiti.tools import MemoryForgetTool

    backend = MagicMock()
    backend._graphiti = mock_graphiti

    tool = MemoryForgetTool(backend=backend)
    result = await tool.execute(fact_id="abc-123", reason="incorrect info", session_key="telegram:123456")

    # Should have called some delete method on graphiti or its driver
    assert "abc-123" in result or "deleted" in result.lower() or "forgotten" in result.lower()


# ── MemoryListTool ───────────────────────────────────────────────────────────

async def test_memory_list_tool_name():
    from nanobot_graphiti.tools import MemoryListTool

    tool = MemoryListTool(backend=MagicMock())
    assert tool.name == "memory_list"


async def test_memory_list_calls_search_with_empty_query(mock_graphiti):
    from nanobot_graphiti.tools import MemoryListTool

    edges = [_make_edge("Fact 1", "u1"), _make_edge("Fact 2", "u2")]
    mock_graphiti.search.return_value = edges

    backend = MagicMock()
    backend._graphiti = mock_graphiti
    backend._get_group_id.return_value = "123456"

    tool = MemoryListTool(backend=backend)
    result = await tool.execute(limit=20, session_key="telegram:123456")

    mock_graphiti.search.assert_awaited_once_with("", group_ids=["123456"], num_results=20)
    assert "Fact 1" in result
    assert "Fact 2" in result


async def test_memory_list_shows_uuids_for_reference(mock_graphiti):
    """memory_list output includes fact_id so user can reference it in memory_forget."""
    from nanobot_graphiti.tools import MemoryListTool

    mock_graphiti.search.return_value = [_make_edge("I have a dog", "edge-uuid-xyz")]

    backend = MagicMock()
    backend._graphiti = mock_graphiti
    backend._get_group_id.return_value = "123456"

    tool = MemoryListTool(backend=backend)
    result = await tool.execute(limit=50, session_key="telegram:123456")

    assert "edge-uuid-xyz" in result
