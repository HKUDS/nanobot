"""Tests for recall_memory tool."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.recall import RecallMemoryTool


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


@pytest.fixture
def provider():
    p = MagicMock()
    p.chat_with_retry = AsyncMock()
    return p


@pytest.fixture
def tool(store, provider):
    return RecallMemoryTool(store=store, provider=provider, model="test-model")


class TestRecallMemoryTool:
    def test_name_and_read_only(self, tool):
        assert tool.name == "recall_memory"
        assert tool.read_only is True

    @pytest.mark.asyncio
    async def test_returns_message_when_memory_empty(self, tool):
        result = await tool.execute(query="anything")
        assert result == "No long-term memory stored yet."

    @pytest.mark.asyncio
    async def test_returns_short_memory_directly(self, tool, store, provider):
        short_content = "# Memory\n- User likes Python\n- Lives in Beijing"
        store.write_memory(short_content)

        result = await tool.execute(query="Python")
        assert result == short_content
        # No LLM call for short content
        provider.chat_with_retry.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_llm_for_long_memory(self, tool, store, provider):
        long_content = "x" * 600  # Above 500-char threshold
        store.write_memory(long_content)

        mock_response = MagicMock()
        mock_response.content = "- relevant fact"
        provider.chat_with_retry.return_value = mock_response

        result = await tool.execute(query="test query")
        assert result == "- relevant fact"
        provider.chat_with_retry.assert_called_once()

        call_kwargs = provider.chat_with_retry.call_args.kwargs
        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["tools"] is None
        assert call_kwargs["max_tokens"] == 1024

        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "Query" in messages[1]["content"]
        assert "test query" in messages[1]["content"]

    @pytest.mark.asyncio
    async def test_returns_raw_on_llm_failure(self, tool, store, provider):
        long_content = "x" * 600
        store.write_memory(long_content)

        provider.chat_with_retry.side_effect = RuntimeError("LLM down")

        result = await tool.execute(query="test query")
        assert result == long_content

    @pytest.mark.asyncio
    async def test_returns_not_found_when_llm_empty(self, tool, store, provider):
        long_content = "x" * 600
        store.write_memory(long_content)

        mock_response = MagicMock()
        mock_response.content = "   "
        provider.chat_with_retry.return_value = mock_response

        result = await tool.execute(query="obscure topic")
        assert result == "(no relevant memory found)"
