from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.providers.custom_provider import CustomProvider


def _make_responses_message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="output_text", text=text)],
    )


def _make_chat_completion(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=[]),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )


@pytest.mark.asyncio
async def test_custom_provider_uses_responses_api() -> None:
    provider = CustomProvider(
        api_key="test-key",
        api_base="https://example.com/v1",
        default_model="gpt-5.2-codex",
    )
    provider._client.responses.create = AsyncMock(
        return_value=SimpleNamespace(
            output=[_make_responses_message("hello from responses")],
            status="completed",
            usage=SimpleNamespace(input_tokens=11, output_tokens=7, total_tokens=18),
        )
    )
    provider._client.chat.completions.create = AsyncMock()

    result = await provider.chat(messages=[{"role": "user", "content": "hello"}])

    assert result.content == "hello from responses"
    assert result.finish_reason == "stop"
    assert result.usage == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }
    provider._client.responses.create.assert_awaited_once()
    provider._client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_custom_provider_falls_back_to_chat_completions() -> None:
    provider = CustomProvider(
        api_key="test-key",
        api_base="https://example.com/v1",
        default_model="gpt-5.2-codex",
    )
    provider._client.responses.create = AsyncMock(
        side_effect=Exception("Unsupported modern protocol: /v1/responses is not supported")
    )
    provider._client.chat.completions.create = AsyncMock(
        return_value=_make_chat_completion("hello from chat completions")
    )

    result = await provider.chat(messages=[{"role": "user", "content": "hello"}])

    assert result.content == "hello from chat completions"
    assert result.finish_reason == "stop"
    provider._client.responses.create.assert_awaited_once()
    provider._client.chat.completions.create.assert_awaited_once()
