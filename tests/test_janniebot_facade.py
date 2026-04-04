"""Tests for the Janniebot programmatic facade."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from janniebot.janniebot import Janniebot, RunResult


def _write_config(tmp_path: Path, overrides: dict | None = None) -> Path:
    data = {
        "providers": {"openrouter": {"apiKey": "sk-test-key"}},
        "agents": {"defaults": {"model": "openai/gpt-4.1"}},
    }
    if overrides:
        data.update(overrides)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data))
    return config_path


def test_from_config_missing_file():
    with pytest.raises(FileNotFoundError):
        Janniebot.from_config("/nonexistent/config.json")


def test_from_config_creates_instance(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Janniebot.from_config(config_path, workspace=tmp_path)
    assert bot._loop is not None
    assert bot._loop.workspace == tmp_path


def test_from_config_default_path():
    from janniebot.config.schema import Config

    with patch("janniebot.config.loader.load_config") as mock_load, \
         patch("janniebot.janniebot._make_provider") as mock_prov:
        mock_load.return_value = Config()
        mock_prov.return_value = MagicMock()
        mock_prov.return_value.get_default_model.return_value = "test"
        mock_prov.return_value.generation.max_tokens = 4096
        Janniebot.from_config()
        mock_load.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_run_returns_result(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Janniebot.from_config(config_path, workspace=tmp_path)

    from janniebot.bus.events import OutboundMessage

    mock_response = OutboundMessage(
        channel="cli", chat_id="direct", content="Hello back!"
    )
    bot._loop.process_direct = AsyncMock(return_value=mock_response)

    result = await bot.run("hi")

    assert isinstance(result, RunResult)
    assert result.content == "Hello back!"
    bot._loop.process_direct.assert_awaited_once_with("hi", session_key="sdk:default")


@pytest.mark.asyncio
async def test_run_with_hooks(tmp_path):
    from janniebot.agent.hook import AgentHook, AgentHookContext
    from janniebot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Janniebot.from_config(config_path, workspace=tmp_path)

    class TestHook(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            pass

    mock_response = OutboundMessage(
        channel="cli", chat_id="direct", content="done"
    )
    bot._loop.process_direct = AsyncMock(return_value=mock_response)

    result = await bot.run("hi", hooks=[TestHook()])

    assert result.content == "done"
    assert bot._loop._extra_hooks == []


@pytest.mark.asyncio
async def test_run_hooks_restored_on_error(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Janniebot.from_config(config_path, workspace=tmp_path)

    from janniebot.agent.hook import AgentHook

    bot._loop.process_direct = AsyncMock(side_effect=RuntimeError("boom"))
    original_hooks = bot._loop._extra_hooks

    with pytest.raises(RuntimeError):
        await bot.run("hi", hooks=[AgentHook()])

    assert bot._loop._extra_hooks is original_hooks


@pytest.mark.asyncio
async def test_run_none_response(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Janniebot.from_config(config_path, workspace=tmp_path)
    bot._loop.process_direct = AsyncMock(return_value=None)

    result = await bot.run("hi")
    assert result.content == ""


def test_workspace_override(tmp_path):
    config_path = _write_config(tmp_path)
    custom_ws = tmp_path / "custom_workspace"
    custom_ws.mkdir()

    bot = Janniebot.from_config(config_path, workspace=custom_ws)
    assert bot._loop.workspace == custom_ws


def test_sdk_make_provider_uses_github_copilot_backend():
    from janniebot.config.schema import Config
    from janniebot.janniebot import _make_provider

    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "github-copilot",
                    "model": "github-copilot/gpt-4.1",
                }
            }
        }
    )

    with patch("janniebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = _make_provider(config)

    assert provider.__class__.__name__ == "GitHubCopilotProvider"


@pytest.mark.asyncio
async def test_run_custom_session_key(tmp_path):
    from janniebot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Janniebot.from_config(config_path, workspace=tmp_path)

    mock_response = OutboundMessage(
        channel="cli", chat_id="direct", content="ok"
    )
    bot._loop.process_direct = AsyncMock(return_value=mock_response)

    await bot.run("hi", session_key="user-alice")
    bot._loop.process_direct.assert_awaited_once_with("hi", session_key="user-alice")


def test_import_from_top_level():
    from janniebot import Janniebot as N
    from janniebot import RunResult as R
    assert N is Janniebot
    assert R is RunResult
