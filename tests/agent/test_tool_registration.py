"""Tests for built-in tool registration rules on AgentLoop."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import WebSearchConfig, WebToolsConfig
from nanobot.providers.base import LLMResponse


def _make_loop(tmp_path: Path, web_config: WebToolsConfig) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.estimate_prompt_tokens.return_value = (10_000, "test")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.generation.max_tokens = 4096
    provider.uses_provider_hosted_web_search = False
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=128_000,
        web_config=web_config,
    )


def test_local_web_search_registered_by_default(tmp_path: Path):
    loop = _make_loop(tmp_path, WebToolsConfig(enable=True))
    assert loop.tools.has("web_search")
    assert loop.tools.has("web_fetch")


def test_local_web_search_skipped_when_hosted(tmp_path: Path):
    """Provider-hosted search suppresses the local web_search tool."""
    cfg = WebToolsConfig(enable=True, search=WebSearchConfig(provider_hosted=True))
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.estimate_prompt_tokens.return_value = (10_000, "test")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.generation.max_tokens = 4096
    provider.uses_provider_hosted_web_search = True
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=128_000,
        web_config=cfg,
    )
    assert not loop.tools.has("web_search")
    # web_fetch must remain so the model can still read full pages.
    assert loop.tools.has("web_fetch")


def test_provider_hosted_config_falls_back_to_local_when_provider_lacks_support(tmp_path: Path):
    """provider_hosted=True is only honored when the active provider supports it."""
    cfg = WebToolsConfig(enable=True, search=WebSearchConfig(provider_hosted=True))
    loop = _make_loop(tmp_path, cfg)
    assert loop.tools.has("web_search")
    # web_fetch must remain so the model can still read full pages.
    assert loop.tools.has("web_fetch")


def test_web_tools_disabled_registers_neither(tmp_path: Path):
    loop = _make_loop(tmp_path, WebToolsConfig(enable=False))
    assert not loop.tools.has("web_search")
    assert not loop.tools.has("web_fetch")
