from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


@pytest.mark.asyncio
async def test_litellm_provider_uses_default_tool_choice_auto_when_tools_present() -> None:
    provider = LiteLLMProvider(provider_name="openai", default_model="gpt-4o-mini")

    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="ok", tool_calls=None, reasoning_content=None, thinking_blocks=None),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    with patch("nanobot.providers.litellm_provider.acompletion", AsyncMock(return_value=fake_response)) as mock_completion:
        result = await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "save_memory", "parameters": {}}}],
        )

    assert result.content == "ok"
    assert mock_completion.await_args.kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_litellm_provider_passes_through_explicit_tool_choice() -> None:
    provider = LiteLLMProvider(provider_name="openai", default_model="gpt-4o-mini")

    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="ok", tool_calls=None, reasoning_content=None, thinking_blocks=None),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    forced_choice = {"type": "function", "function": {"name": "save_memory"}}

    with patch("nanobot.providers.litellm_provider.acompletion", AsyncMock(return_value=fake_response)) as mock_completion:
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "save_memory", "parameters": {}}}],
            tool_choice=forced_choice,
        )

    assert mock_completion.await_args.kwargs["tool_choice"] == forced_choice
