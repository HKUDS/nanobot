"""Contract tests for LLM provider abstractions.

These tests verify that:
1. ``LLMProvider`` subclasses honour the abstract interface contract.
2. ``LLMResponse`` and ``StreamChunk`` dataclasses behave consistently.
3. ``ToolCallRequest`` dataclass has required fields.
"""

from __future__ import annotations

import inspect
from typing import Any

from nanobot.providers.base import LLMProvider, LLMResponse, StreamChunk, ToolCallRequest

# ---------------------------------------------------------------------------
# Contract: LLMProvider ABC
# ---------------------------------------------------------------------------


class TestLLMProviderContract:
    """LLMProvider must define the required abstract methods."""

    def test_chat_is_abstract(self):
        assert inspect.isabstract(LLMProvider)
        abstract_methods = {
            name
            for name, _ in inspect.getmembers(LLMProvider)
            if getattr(getattr(LLMProvider, name, None), "__isabstractmethod__", False)
        }
        assert "chat" in abstract_methods, "LLMProvider.chat must be abstract"
        assert "get_default_model" in abstract_methods, (
            "LLMProvider.get_default_model must be abstract"
        )

    def test_chat_signature_has_expected_params(self):
        sig = inspect.signature(LLMProvider.chat)
        params = list(sig.parameters.keys())
        assert "messages" in params, "chat() must accept 'messages'"
        assert "tools" in params, "chat() must accept 'tools'"
        assert "model" in params, "chat() must accept 'model'"
        assert "max_tokens" in params, "chat() must accept 'max_tokens'"
        assert "temperature" in params, "chat() must accept 'temperature'"

    def test_stream_chat_has_default_implementation(self):
        """stream_chat should have a default fallback (not abstract)."""
        abstract_methods = {
            name
            for name, _ in inspect.getmembers(LLMProvider)
            if getattr(getattr(LLMProvider, name, None), "__isabstractmethod__", False)
        }
        assert "stream_chat" not in abstract_methods, (
            "stream_chat should not be abstract — it has a default fallback"
        )

    def test_sanitize_empty_content_is_static(self):
        """_sanitize_empty_content should be a static method available to all providers."""
        assert hasattr(LLMProvider, "_sanitize_empty_content")

    def test_sanitize_empty_content_replaces_empty_strings(self):
        messages = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
            {"role": "user", "content": "hello"},
        ]
        result = LLMProvider._sanitize_empty_content(messages)
        assert result[0]["content"] == "(empty)"
        assert result[1]["content"] is None  # assistant with tool_calls gets None
        assert result[2]["content"] == "hello"  # non-empty preserved


# ---------------------------------------------------------------------------
# Contract: Concrete provider compliance (ScriptedProvider for testing)
# ---------------------------------------------------------------------------


class _TestProvider(LLMProvider):
    """Minimal concrete provider for contract validation."""

    def __init__(self):
        super().__init__()

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        return LLMResponse(content="test response")


class TestConcreteProviderContract:
    """A concrete LLMProvider must satisfy the base class contract."""

    def test_instantiation(self):
        provider = _TestProvider()
        assert isinstance(provider, LLMProvider)

    def test_get_default_model_returns_string(self):
        provider = _TestProvider()
        model = provider.get_default_model()
        assert isinstance(model, str)
        assert len(model) > 0

    async def test_chat_returns_llm_response(self):
        provider = _TestProvider()
        result = await provider.chat(
            messages=[{"role": "user", "content": "hi"}],
        )
        assert isinstance(result, LLMResponse)
        assert result.content is not None

    async def test_stream_chat_yields_stream_chunks(self):
        """Default stream_chat fallback should yield StreamChunk objects."""
        provider = _TestProvider()
        chunks = []
        async for chunk in provider.stream_chat(
            messages=[{"role": "user", "content": "hi"}],
        ):
            chunks.append(chunk)
        assert len(chunks) >= 1
        assert isinstance(chunks[0], StreamChunk)
        assert chunks[-1].done is True


# ---------------------------------------------------------------------------
# Contract: LLMResponse dataclass consistency
# ---------------------------------------------------------------------------


class TestLLMResponseContract:
    """LLMResponse must maintain consistent behavior."""

    def test_defaults(self):
        r = LLMResponse(content="hello")
        assert r.content == "hello"
        assert r.tool_calls == []
        assert r.finish_reason == "stop"
        assert r.usage == {}
        assert r.reasoning_content is None

    def test_has_tool_calls_empty(self):
        r = LLMResponse(content="hello")
        assert r.has_tool_calls is False

    def test_has_tool_calls_present(self):
        r = LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="1", name="test", arguments={})],
        )
        assert r.has_tool_calls is True

    def test_usage_dict(self):
        r = LLMResponse(
            content="hi",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
        assert r.usage["prompt_tokens"] == 10


# ---------------------------------------------------------------------------
# Contract: StreamChunk dataclass
# ---------------------------------------------------------------------------


class TestStreamChunkContract:
    """StreamChunk must have required fields with correct defaults."""

    def test_defaults(self):
        c = StreamChunk()
        assert c.content_delta is None
        assert c.reasoning_delta is None
        assert c.finish_reason is None
        assert c.usage == {}
        assert c.tool_calls == []
        assert c.done is False

    def test_done_chunk(self):
        c = StreamChunk(content_delta="end", done=True, finish_reason="stop")
        assert c.done is True
        assert c.finish_reason == "stop"


# ---------------------------------------------------------------------------
# Contract: ToolCallRequest dataclass
# ---------------------------------------------------------------------------


class TestToolCallRequestContract:
    """ToolCallRequest must have id, name, and arguments."""

    def test_required_fields(self):
        tc = ToolCallRequest(id="abc", name="read_file", arguments={"path": "/tmp/x"})
        assert tc.id == "abc"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/tmp/x"}

    def test_empty_arguments(self):
        tc = ToolCallRequest(id="1", name="list_dir", arguments={})
        assert tc.arguments == {}
