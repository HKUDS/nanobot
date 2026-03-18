from __future__ import annotations

from typing import Any

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class _DummyProvider(LLMProvider):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content="ok",
            tool_calls=[ToolCallRequest(id="t1", name="read", arguments={})],
            finish_reason="stop",
            usage={"total_tokens": 3},
            reasoning_content="r",
        )

    def get_default_model(self) -> str:
        return "dummy"


def test_sanitize_empty_content_variants() -> None:
    msgs = [
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "x"}]},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": ""},
                {"type": "input_text", "text": ""},
                {"type": "text", "text": "keep"},
            ],
        },
    ]
    out = _DummyProvider._sanitize_empty_content(msgs)
    assert out[0]["content"] == "(empty)"
    assert out[1]["content"] is None
    assert isinstance(out[2]["content"], list)
    assert out[2]["content"][0]["text"] == "keep"


async def test_stream_chat_default_fallback() -> None:
    provider = _DummyProvider(api_key=None)
    chunks = [
        chunk
        async for chunk in provider.stream_chat(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            model=None,
        )
    ]
    assert len(chunks) == 1
    assert chunks[0].done is True
    assert chunks[0].content_delta == "ok"
    assert chunks[0].tool_calls and chunks[0].tool_calls[0].name == "read"


async def test_aclose_default_noop() -> None:
    provider = _DummyProvider(api_key=None)
    await provider.aclose()
