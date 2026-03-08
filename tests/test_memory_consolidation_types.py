"""Test MemoryStore.consolidate() handles non-string tool call arguments.

Regression test for https://github.com/HKUDS/nanobot/issues/1042
When memory consolidation receives dict values instead of strings from the LLM
tool call response, it should serialize them to JSON instead of raising TypeError.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_session(message_count: int = 30, memory_window: int = 50):
    """Create a mock session with messages."""
    session = MagicMock()
    session.messages = [
        {"role": "user", "content": f"msg{i}", "timestamp": "2026-01-01 00:00"}
        for i in range(message_count)
    ]
    session.last_consolidated = 0
    return session


def _make_tool_response(history_entry):
    """Create an LLMResponse with a save_history tool call."""
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(
                id="call_1",
                name="save_history",
                arguments={
                    "history_entry": history_entry,
                },
            )
        ],
    )


class TestMemoryConsolidationTypeHandling:
    """Test that consolidation handles various argument types correctly."""

    @pytest.mark.asyncio
    async def test_string_arguments_work(self, tmp_path: Path) -> None:
        """Normal case: LLM returns string arguments."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=_make_tool_response(
                history_entry="[2026-01-01] User discussed testing.",
            )
        )
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert store.history_file.exists()
        assert "[2026-01-01] User discussed testing." in store.history_file.read_text()

    @pytest.mark.asyncio
    async def test_dict_arguments_serialized_to_json(self, tmp_path: Path) -> None:
        """Issue #1042: LLM returns dict instead of string — must not raise TypeError."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=_make_tool_response(
                history_entry={"timestamp": "2026-01-01", "summary": "User discussed testing."},
            )
        )
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert store.history_file.exists()
        history_content = store.history_file.read_text()
        parsed = json.loads(history_content.strip())
        assert parsed["summary"] == "User discussed testing."

    @pytest.mark.asyncio
    async def test_string_arguments_as_raw_json(self, tmp_path: Path) -> None:
        """Some providers return arguments as a JSON string instead of parsed dict."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()

        # Simulate arguments being a JSON string (not yet parsed)
        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_history",
                    arguments=json.dumps({
                        "history_entry": "[2026-01-01] User discussed testing.",
                    }),
                )
            ],
        )
        provider.chat = AsyncMock(return_value=response)
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert "User discussed testing." in store.history_file.read_text()

    @pytest.mark.asyncio
    async def test_no_tool_call_returns_false(self, tmp_path: Path) -> None:
        """When LLM doesn't use the save_history tool, return False."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(content="I summarized the conversation.", tool_calls=[])
        )
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is False
        assert not store.history_file.exists()

    @pytest.mark.asyncio
    async def test_skips_when_few_messages(self, tmp_path: Path) -> None:
        """Consolidation should be a no-op when messages < keep_count."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        session = _make_session(message_count=10)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        provider.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_arguments_extracts_first_dict(self, tmp_path: Path) -> None:
        """Some providers return arguments as a list - extract first element if it's a dict."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()

        # Simulate arguments being a list containing a dict
        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_history",
                    arguments=[{
                        "history_entry": "[2026-01-01] User discussed testing.",
                    }],
                )
            ],
        )
        provider.chat = AsyncMock(return_value=response)
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert "User discussed testing." in store.history_file.read_text()

    @pytest.mark.asyncio
    async def test_list_arguments_empty_list_returns_false(self, tmp_path: Path) -> None:
        """Empty list arguments should return False."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()

        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_history",
                    arguments=[],
                )
            ],
        )
        provider.chat = AsyncMock(return_value=response)
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is False

    @pytest.mark.asyncio
    async def test_list_arguments_non_dict_content_returns_false(self, tmp_path: Path) -> None:
        """List with non-dict content should return False."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()

        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_history",
                    arguments=["string", "content"],
                )
            ],
        )
        provider.chat = AsyncMock(return_value=response)
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is False

    @pytest.mark.asyncio
    async def test_truncated_response_returns_false(self, tmp_path: Path) -> None:
        """When LLM response is truncated (finish_reason='length'), return False."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()

        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_history",
                    arguments={"history_entry": "[2026-01-01] Truncated..."},
                )
            ],
            finish_reason="length",  # Response was truncated
        )
        provider.chat = AsyncMock(return_value=response)
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is False
        assert not store.history_file.exists()
