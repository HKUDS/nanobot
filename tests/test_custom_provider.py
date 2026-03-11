from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.providers.custom_provider import CustomProvider


def _fake_response(content: str = "ok", with_usage: bool = True, args: str = "{}"):
    tc = SimpleNamespace(
        id="tc1",
        function=SimpleNamespace(name="read_file", arguments=args),
    )
    msg = SimpleNamespace(content=content, tool_calls=[tc], reasoning_content="think")
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3) if with_usage else None
    return SimpleNamespace(choices=[choice], usage=usage)


@pytest.mark.asyncio
async def test_custom_provider_chat_success() -> None:
    provider = CustomProvider(api_key="k", api_base="http://localhost:8000/v1", default_model="m")
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=_fake_response())))
    )

    out = await provider.chat(messages=[{"role": "user", "content": "hello"}], tools=[{"type": "function"}])
    assert out.content == "ok"
    assert out.finish_reason == "stop"
    assert out.tool_calls and out.tool_calls[0].name == "read_file"
    assert out.usage["total_tokens"] == 3


@pytest.mark.asyncio
async def test_custom_provider_chat_error() -> None:
    provider = CustomProvider(api_key="k", api_base="http://localhost:8000/v1", default_model="m")
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
        )
    )

    out = await provider.chat(messages=[{"role": "user", "content": "hello"}])
    assert out.finish_reason == "error"
    assert "Error:" in (out.content or "")


def test_custom_provider_parse_without_usage_and_non_json_args() -> None:
    provider = CustomProvider(api_key="k", api_base="http://localhost:8000/v1", default_model="m")
    parsed = provider._parse(_fake_response(with_usage=False, args="not-json"))
    assert parsed.usage == {}
    assert parsed.tool_calls[0].arguments == ""
