"""Tests for AtomGit provider streaming implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.atomgit_provider import AtomGitProvider
from nanobot.providers.base import LLMResponse


def _make_chunk(content=None, reasoning=None, tool_calls=None, finish_reason=None):
    """Build a mock streaming chunk."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls or []
    # Simulate reasoning attribute present on some providers
    delta.reasoning = reasoning
    delta.reasoning_content = None

    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason

    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = None
    return chunk


def _make_tool_call_chunk(index, id=None, name=None, arguments=None):
    """Build a mock tool-call delta chunk."""
    fn = MagicMock()
    fn.name = name
    fn.arguments = arguments

    tc = MagicMock()
    tc.index = index
    tc.id = id
    tc.function = fn
    return tc


class _MockStream:
    """Async iterable that yields preset chunks (simulates AsyncStream)."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_chat_uses_streaming():
    """Provider must always use stream=True via .create() to cope with SSE-only AtomGit API."""
    provider = AtomGitProvider(api_key="test-key")

    chunks = [
        _make_chunk(content="Hello"),
        _make_chunk(content=" world", finish_reason="stop"),
    ]

    with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock, return_value=_MockStream(chunks)) as mock_create:
        result = await provider.chat([{"role": "user", "content": "Hi"}])

    # create() must have been called with stream=True
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args[1]
    assert call_kwargs.get("stream") is True

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello world"
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_chat_accumulates_content_chunks():
    """Multiple content deltas are concatenated correctly."""
    provider = AtomGitProvider(api_key="test-key")

    chunks = [
        _make_chunk(content="The sky "),
        _make_chunk(content="is blue"),
        _make_chunk(finish_reason="stop"),
    ]

    with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock, return_value=_MockStream(chunks)):
        result = await provider.chat([{"role": "user", "content": "fact?"}])

    assert result.content == "The sky is blue"


@pytest.mark.asyncio
async def test_chat_accumulates_tool_calls():
    """Tool-call deltas arriving across multiple chunks are merged correctly."""
    provider = AtomGitProvider(api_key="test-key")

    tc0_id = _make_tool_call_chunk(0, id="call_abc", name="get_weather", arguments=None)
    tc0_args = _make_tool_call_chunk(0, id=None, name=None, arguments='{"loc')
    tc0_args2 = _make_tool_call_chunk(0, id=None, name=None, arguments='ation":"SF"}')

    chunks = [
        _make_chunk(tool_calls=[tc0_id]),
        _make_chunk(tool_calls=[tc0_args]),
        _make_chunk(tool_calls=[tc0_args2], finish_reason="tool_calls"),
    ]

    with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock, return_value=_MockStream(chunks)):
        result = await provider.chat([{"role": "user", "content": "weather?"}])

    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.id == "call_abc"
    assert tc.name == "get_weather"
    assert tc.arguments == {"location": "SF"}


@pytest.mark.asyncio
async def test_chat_accumulates_reasoning():
    """Reasoning deltas (chain-of-thought) are concatenated into reasoning_content."""
    provider = AtomGitProvider(api_key="test-key")

    chunks = [
        _make_chunk(reasoning="thinking..."),
        _make_chunk(reasoning=" done", content="Answer", finish_reason="stop"),
    ]

    with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock, return_value=_MockStream(chunks)):
        result = await provider.chat([{"role": "user", "content": "think"}])

    assert result.reasoning_content == "thinking... done"
    assert result.content == "Answer"


@pytest.mark.asyncio
async def test_chat_error_returns_error_response():
    """Exceptions during streaming are caught and returned as error LLMResponse."""
    provider = AtomGitProvider(api_key="test-key")

    with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock, side_effect=RuntimeError("connection refused")):
        result = await provider.chat([{"role": "user", "content": "hi"}])

    assert result.finish_reason == "error"
    assert "connection refused" in result.content


def test_get_default_model():
    provider = AtomGitProvider(api_key="k", default_model="zai/custom")
    assert provider.get_default_model() == "zai/custom"


def test_default_api_base():
    provider = AtomGitProvider(api_key="k")
    assert provider.api_base == AtomGitProvider.DEFAULT_API_BASE
