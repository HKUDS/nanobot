from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.custom_provider import CustomProvider
from nanobot.providers.openai_codex_provider import _normalize_codex_tool_choice


@pytest.mark.asyncio
async def test_custom_provider_uses_default_tool_choice_auto_when_tools_present() -> None:
    provider = CustomProvider(api_key="test-key", api_base="http://localhost:8000/v1", default_model="test-model")

    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="ok", tool_calls=None),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    with patch.object(provider._client.chat.completions, "create", AsyncMock(return_value=fake_response)) as mock_create:
        result = await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "save_memory", "parameters": {}}}],
        )

    assert result.content == "ok"
    assert mock_create.await_args.kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_custom_provider_passes_through_explicit_tool_choice() -> None:
    provider = CustomProvider(api_key="test-key", api_base="http://localhost:8000/v1", default_model="test-model")

    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="ok", tool_calls=None),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    forced_choice = {"type": "function", "function": {"name": "save_memory"}}

    with patch.object(provider._client.chat.completions, "create", AsyncMock(return_value=fake_response)) as mock_create:
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "save_memory", "parameters": {}}}],
            tool_choice=forced_choice,
        )

    assert mock_create.await_args.kwargs["tool_choice"] == forced_choice


def test_codex_tool_choice_keeps_supported_string_values() -> None:
    assert _normalize_codex_tool_choice("auto") == "auto"
    assert _normalize_codex_tool_choice("required") == "required"


def test_codex_tool_choice_downgrades_dict_form_to_auto() -> None:
    assert _normalize_codex_tool_choice(
        {"type": "function", "function": {"name": "save_memory"}}
    ) == "auto"
