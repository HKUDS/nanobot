"""Tests for LiteLLMProvider request/response behavior."""

import os
import types

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


async def test_chat_clamps_max_tokens_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat should clamp max_tokens values below one before calling LiteLLM."""
    captured: dict[str, object] = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="ok", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", fake_acompletion)

    provider = LiteLLMProvider(api_key="test-key", default_model="gpt-4o-mini")
    response = await provider.chat(messages=[{"role": "user", "content": "hi"}], max_tokens=0)

    assert captured["max_tokens"] == 1
    assert response.content == "ok"


async def test_chat_returns_error_response_on_completion_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chat should convert LiteLLM exceptions into an error-shaped LLMResponse."""

    async def fake_acompletion(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", fake_acompletion)

    provider = LiteLLMProvider(api_key="test-key", default_model="gpt-4o-mini")
    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert response.content == "Error calling LLM: boom"


def test_parse_response_reads_tool_calls_and_usage() -> None:
    """_parse_response should parse tool calls JSON and usage fields from LiteLLM responses."""
    provider = LiteLLMProvider(default_model="gpt-4o-mini")

    response = types.SimpleNamespace(
        choices=[
            types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content="tool response",
                    tool_calls=[
                        types.SimpleNamespace(
                            id="tool_1",
                            function=types.SimpleNamespace(
                                name="search",
                                arguments='{"query":"nanobot"}',
                            ),
                        )
                    ],
                    reasoning_content="reasoning",
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=types.SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )

    parsed = provider._parse_response(response)

    assert parsed.content == "tool response"
    assert parsed.finish_reason == "tool_calls"
    assert parsed.reasoning_content == "reasoning"
    assert parsed.usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].id == "tool_1"
    assert parsed.tool_calls[0].name == "search"
    assert parsed.tool_calls[0].arguments == {"query": "nanobot"}


def test_provider_sets_env_and_resolves_model_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider should map model to prefixed route and export provider API key env."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    provider = LiteLLMProvider(api_key="dash-key", default_model="qwen-max")

    assert provider._resolve_model("qwen-max") == "dashscope/qwen-max"
    assert provider.get_default_model() == "qwen-max"
    assert provider._gateway is None
    assert provider.api_key == "dash-key"
    assert provider.api_base is None
    assert os.environ["DASHSCOPE_API_KEY"] == "dash-key"
