from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


def _make_provider(default_model: str, reply: str) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.estimate_prompt_tokens.return_value = (0, "test-counter")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content=reply, tool_calls=[]))
    return provider


@pytest.mark.asyncio
async def test_model_command_sets_session_override_and_uses_selected_provider(tmp_path) -> None:
    default_provider = _make_provider("anthropic/claude-opus-4-5", "default")
    selected_provider = _make_provider("openai/gpt-4o-mini", "selected")

    def provider_factory(model: str):
        if model == "openai/gpt-4o-mini":
            return selected_provider
        return default_provider

    loop = AgentLoop(
        bus=MessageBus(),
        provider=default_provider,
        workspace=tmp_path,
        model="anthropic/claude-opus-4-5",
        provider_factory=provider_factory,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    set_response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/model openai/gpt-4o-mini")
    )

    assert set_response is not None
    assert "openai/gpt-4o-mini" in set_response.content

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello")
    )

    assert response is not None
    assert response.content == "selected"
    selected_provider.chat_with_retry.assert_awaited()
    assert selected_provider.chat_with_retry.await_args.kwargs["model"] == "openai/gpt-4o-mini"
    assert not default_provider.chat_with_retry.await_count


@pytest.mark.asyncio
async def test_model_command_without_argument_reports_current_and_default_model(tmp_path) -> None:
    provider = _make_provider("anthropic/claude-opus-4-5", "default")

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="anthropic/claude-opus-4-5",
    )

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/model")
    )

    assert response is not None
    assert "anthropic/claude-opus-4-5" in response.content
    assert "Default model" in response.content


@pytest.mark.asyncio
async def test_model_command_default_clears_session_override(tmp_path) -> None:
    default_provider = _make_provider("anthropic/claude-opus-4-5", "default")
    selected_provider = _make_provider("openai/gpt-4o-mini", "selected")

    def provider_factory(model: str):
        if model == "openai/gpt-4o-mini":
            return selected_provider
        return default_provider

    loop = AgentLoop(
        bus=MessageBus(),
        provider=default_provider,
        workspace=tmp_path,
        model="anthropic/claude-opus-4-5",
        provider_factory=provider_factory,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/model openai/gpt-4o-mini")
    )
    reset_response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/model default")
    )

    assert reset_response is not None
    assert "anthropic/claude-opus-4-5" in reset_response.content

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello")
    )

    assert response is not None
    assert response.content == "default"
    default_provider.chat_with_retry.assert_awaited()
    assert default_provider.chat_with_retry.await_args.kwargs["model"] == "anthropic/claude-opus-4-5"
