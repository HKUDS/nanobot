from types import SimpleNamespace

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


def _chunk(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list[SimpleNamespace] | None = None,
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


@pytest.mark.asyncio
async def test_chat_fallbacks_to_stream_and_merges_tool_call_chunks(monkeypatch) -> None:
    provider = LiteLLMProvider(default_model="test-model")
    calls: list[dict] = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs.copy())
        if not kwargs.get("stream"):
            raise RuntimeError("primary request failed")

        async def _stream():
            yield _chunk(
                content="Hello",
                reasoning_content="r1-",
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id="call_1",
                        function=SimpleNamespace(name="message", arguments='{"x":'),
                    )
                ],
            )
            yield _chunk(
                content=" world",
                finish_reason="tool_calls",
                reasoning_content="r2",
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id=None,
                        function=SimpleNamespace(name=None, arguments='"y"}'),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            )

        return _stream()

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", fake_acompletion)

    result = await provider.chat(messages=[{"role": "user", "content": "hi"}], tools=[])

    assert len(calls) == 2
    assert calls[0].get("stream") is None
    assert calls[1]["stream"] is True
    assert result.content == "Hello world"
    assert result.finish_reason == "tool_calls"
    assert result.reasoning_content == "r1-r2"
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "message"
    assert result.tool_calls[0].arguments == {"x": "y"}


@pytest.mark.asyncio
async def test_chat_returns_error_with_exception_type_when_stream_fallback_fails(monkeypatch) -> None:
    provider = LiteLLMProvider(default_model="test-model")

    async def fake_acompletion(**kwargs):
        if kwargs.get("stream"):
            raise ValueError("stream broken")
        raise RuntimeError("primary request failed")

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", fake_acompletion)

    result = await provider.chat(messages=[{"role": "user", "content": "hi"}], tools=[])

    assert result.finish_reason == "error"
    assert result.content == "Error calling LLM: ValueError: stream broken"
    assert result.tool_calls == []


def test_format_exception_without_message() -> None:
    provider = LiteLLMProvider(default_model="test-model")

    class NoMessageError(Exception):
        pass

    assert provider._format_exception(NoMessageError()) == "NoMessageError"


def test_extract_usage_supports_openai_prompt_cache_details() -> None:
    provider = LiteLLMProvider(default_model="test-model")
    usage = SimpleNamespace(
        prompt_tokens=120,
        completion_tokens=12,
        total_tokens=132,
        prompt_tokens_details=SimpleNamespace(cached_tokens=90),
    )

    assert provider._extract_usage(usage) == {
        "prompt_tokens": 120,
        "completion_tokens": 12,
        "total_tokens": 132,
        "cache_creation_input_tokens": 30,
        "cache_read_input_tokens": 90,
    }


def test_extract_usage_supports_anthropic_cache_fields() -> None:
    provider = LiteLLMProvider(default_model="test-model")
    usage = SimpleNamespace(
        input_tokens=200,
        output_tokens=15,
        cache_creation_input_tokens=50,
        cache_read_input_tokens=120,
    )

    assert provider._extract_usage(usage) == {
        "prompt_tokens": 200,
        "completion_tokens": 15,
        "total_tokens": 215,
        "cache_creation_input_tokens": 50,
        "cache_read_input_tokens": 120,
    }
