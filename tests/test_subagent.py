"""Tests for subagent execution and model delegation."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.subagent import SubagentManager
from nanobot.config.schema import SubagentConfig
from nanobot.providers.base import LLMProvider


@pytest.fixture
def mock_provider():
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "main/model"
    mock_response = MagicMock()
    mock_response.has_tool_calls = False
    mock_response.content = "Task finished by main provider"
    mock_response.finish_reason = "stop"
    provider.chat_with_retry = AsyncMock(return_value=mock_response)
    return provider


@pytest.mark.asyncio
async def test_subagent_spawn_with_delegated_model(tmp_path: Path, mock_provider: LLMProvider):
    sub_config = SubagentConfig(
        model="claude-3-haiku",
        provider="anthropic",
        description="Fast coder",
        temperature=0.2,
        max_tokens=2048
    )

    mock_factory_provider = MagicMock(spec=LLMProvider)
    mock_response = MagicMock()
    mock_response.has_tool_calls = False
    mock_response.content = "Done via haiku"
    mock_factory_provider.chat_with_retry = AsyncMock(return_value=mock_response)

    def provider_factory(model_str, provider_override):
        if model_str == "claude-3-haiku" and provider_override == "anthropic":
            return mock_factory_provider
        return mock_provider

    bus = MagicMock()

    manager = SubagentManager(
        provider=mock_provider,
        workspace=tmp_path,
        bus=bus,
        subagent_configs={"coder": sub_config},
        provider_factory=provider_factory
    )

    # Spawn specific subagent
    await manager.spawn("Write a script", subagent_id="coder")

    # Wait to allow background loop iteration
    await asyncio.sleep(0.1)

    # Ensure delegated factory was queried with correct subagent parameters
    mock_factory_provider.chat_with_retry.assert_called_once()
    kwargs = mock_factory_provider.chat_with_retry.call_args.kwargs
    assert kwargs["model"] == "claude-3-haiku"
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 2048

    # The main provider should not have been called
    mock_provider.chat_with_retry.assert_not_called()


@pytest.mark.asyncio
async def test_subagent_fallback(tmp_path: Path, mock_provider: LLMProvider):
    bus = MagicMock()

    # Initialize without subagent configs
    manager = SubagentManager(
        provider=mock_provider,
        workspace=tmp_path,
        bus=bus,
        subagent_configs={},
        provider_factory=None
    )

    # Spawn default background agent
    await manager.spawn("Test fallback")
    await asyncio.sleep(0.1)

    # Validate main provider was used with default parameters
    mock_provider.chat_with_retry.assert_called_once()
    kwargs = mock_provider.chat_with_retry.call_args.kwargs
    assert kwargs["model"] == "main/model"
    assert kwargs["temperature"] == 0.1
