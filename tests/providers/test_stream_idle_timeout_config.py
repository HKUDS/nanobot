from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import nanobot.providers.openai_codex_provider as codex_provider
from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.base import (
    DEFAULT_STREAM_IDLE_TIMEOUT_S,
    MAX_STREAM_IDLE_TIMEOUT_S,
    resolve_stream_idle_timeout_s,
)
from nanobot.providers.bedrock_provider import BedrockProvider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


class _AsyncStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks
        self._idx = 0

    def __aiter__(self) -> _AsyncStream:
        return self

    async def __anext__(self) -> Any:
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


class _AnthropicStream(_AsyncStream):
    def __init__(self, chunks: list[Any]) -> None:
        super().__init__(chunks)
        self.get_final_message = AsyncMock(return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        ))

    async def __aenter__(self) -> _AnthropicStream:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        pass


class _BedrockClient:
    def converse_stream(self, **_kwargs: Any) -> dict[str, Any]:
        return {"stream": iter([
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "ok"}}},
            {"messageStop": {"stopReason": "end_turn"}},
        ])}


def test_stream_idle_timeout_parser_rejects_invalid_values() -> None:
    assert resolve_stream_idle_timeout_s(env_value="abc") == DEFAULT_STREAM_IDLE_TIMEOUT_S
    assert resolve_stream_idle_timeout_s(env_value="-1") == DEFAULT_STREAM_IDLE_TIMEOUT_S
    assert resolve_stream_idle_timeout_s(env_value="0") == DEFAULT_STREAM_IDLE_TIMEOUT_S


def test_stream_idle_timeout_parser_accepts_and_clamps_numeric_values() -> None:
    assert resolve_stream_idle_timeout_s(env_value="1.5") == 1.5
    assert resolve_stream_idle_timeout_s(env_value="7200") == MAX_STREAM_IDLE_TIMEOUT_S


@pytest.mark.asyncio
async def test_openai_compat_stream_ignores_invalid_idle_timeout_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "abc")
    provider = OpenAICompatProvider(api_key="sk-test", api_base="https://example.com/v1")

    chunk = SimpleNamespace(
        choices=[SimpleNamespace(
            delta=SimpleNamespace(
                content="ok",
                reasoning_content=None,
                reasoning=None,
                tool_calls=None,
                function_call=None,
            ),
            finish_reason="stop",
        )],
        usage=None,
    )
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=_AsyncStream([chunk])),
        )),
    )

    result = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "ok"


@pytest.mark.asyncio
async def test_anthropic_stream_ignores_invalid_idle_timeout_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "abc")
    provider = AnthropicProvider(api_key="sk-test")
    provider._client = MagicMock()
    provider._client.messages.stream = MagicMock(return_value=_AnthropicStream([]))

    result = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "ok"


@pytest.mark.asyncio
async def test_bedrock_stream_ignores_invalid_idle_timeout_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "abc")
    provider = BedrockProvider(region="us-east-1", client=_BedrockClient())

    result = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "ok"


@pytest.mark.asyncio
async def test_codex_stream_ignores_invalid_idle_timeout_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "abc")
    original_client = httpx.AsyncClient
    seen: dict[str, float] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    def fake_client(*, timeout: float, verify: bool) -> httpx.AsyncClient:
        seen["timeout"] = timeout
        return original_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(codex_provider.httpx, "AsyncClient", fake_client)

    await codex_provider._request_codex(
        "https://codex.example/responses",
        {},
        {"input": []},
        verify=True,
    )

    assert seen["timeout"] == DEFAULT_STREAM_IDLE_TIMEOUT_S
