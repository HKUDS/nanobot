"""Tests for the Nanobot programmatic facade."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.nanobot import Nanobot, RunResult


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
        Nanobot.from_config("/nonexistent/config.json")


def test_from_config_creates_instance(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)
    assert bot._loop is not None
    assert bot._loop.workspace == tmp_path


def test_from_config_default_path():
    from nanobot.config.schema import Config

    with patch("nanobot.config.loader.load_config") as mock_load, \
         patch("nanobot.nanobot._make_provider") as mock_prov:
        mock_load.return_value = Config()
        mock_prov.return_value = MagicMock()
        mock_prov.return_value.get_default_model.return_value = "test"
        mock_prov.return_value.generation.max_tokens = 4096
        Nanobot.from_config()
        mock_load.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_run_returns_result(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    from nanobot.bus.events import OutboundMessage

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
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

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
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    from nanobot.agent.hook import AgentHook

    bot._loop.process_direct = AsyncMock(side_effect=RuntimeError("boom"))
    original_hooks = bot._loop._extra_hooks

    with pytest.raises(RuntimeError):
        await bot.run("hi", hooks=[AgentHook()])

    assert bot._loop._extra_hooks is original_hooks


@pytest.mark.asyncio
async def test_run_none_response(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)
    bot._loop.process_direct = AsyncMock(return_value=None)

    result = await bot.run("hi")
    assert result.content == ""


def test_workspace_override(tmp_path):
    config_path = _write_config(tmp_path)
    custom_ws = tmp_path / "custom_workspace"
    custom_ws.mkdir()

    bot = Nanobot.from_config(config_path, workspace=custom_ws)
    assert bot._loop.workspace == custom_ws


def test_sdk_make_provider_uses_github_copilot_backend():
    from nanobot.config.schema import Config
    from nanobot.nanobot import _make_provider

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

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = _make_provider(config)

    assert provider.__class__.__name__ == "GitHubCopilotProvider"


@pytest.mark.asyncio
async def test_run_custom_session_key(tmp_path):
    from nanobot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    mock_response = OutboundMessage(
        channel="cli", chat_id="direct", content="ok"
    )
    bot._loop.process_direct = AsyncMock(return_value=mock_response)

    await bot.run("hi", session_key="user-alice")
    bot._loop.process_direct.assert_awaited_once_with("hi", session_key="user-alice")


def test_import_from_top_level():
    import nanobot

    assert nanobot.Nanobot is Nanobot
    assert nanobot.RunResult is RunResult


# ---------------------------------------------------------------------------
# RunResult.tools_used / messages — populated from the agent iterations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_populates_tools_used_across_iterations(tmp_path):
    """tools_used collects every tool name fired across all iterations, in order."""
    from nanobot.agent.hook import AgentHookContext
    from nanobot.bus.events import OutboundMessage
    from nanobot.providers.base import ToolCallRequest

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    async def fake_process_direct(message, *, session_key):
        # Whatever hooks the SDK installed are now on the loop.
        extras = bot._loop._extra_hooks
        messages = [{"role": "user", "content": message}]
        ctx1 = AgentHookContext(iteration=0, messages=messages)
        ctx1.tool_calls = [
            ToolCallRequest(id="c1", name="read_file", arguments={}),
            ToolCallRequest(id="c2", name="glob", arguments={}),
        ]
        for h in extras:
            await h.after_iteration(ctx1)
        messages.append({"role": "assistant", "content": "ok"})
        ctx2 = AgentHookContext(iteration=1, messages=messages)
        ctx2.tool_calls = [ToolCallRequest(id="c3", name="web_fetch", arguments={})]
        for h in extras:
            await h.after_iteration(ctx2)
        return OutboundMessage(channel="cli", chat_id="direct", content="final")

    bot._loop.process_direct = fake_process_direct
    result = await bot.run("do stuff")
    assert result.content == "final"
    assert result.tools_used == ["read_file", "glob", "web_fetch"]


@pytest.mark.asyncio
async def test_run_populates_final_messages(tmp_path):
    """messages reflects the agent's message list at the last iteration."""
    from nanobot.agent.hook import AgentHookContext
    from nanobot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    async def fake_process_direct(message, *, session_key):
        extras = bot._loop._extra_hooks
        messages = [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "hi there"},
        ]
        ctx = AgentHookContext(iteration=0, messages=messages)
        for h in extras:
            await h.after_iteration(ctx)
        return OutboundMessage(channel="cli", chat_id="direct", content="hi there")

    bot._loop.process_direct = fake_process_direct
    result = await bot.run("hello")
    assert result.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


@pytest.mark.asyncio
async def test_run_no_iterations_leaves_defaults_empty(tmp_path):
    """If process_direct never triggers after_iteration, tools_used/messages stay []."""
    from nanobot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)
    bot._loop.process_direct = AsyncMock(
        return_value=OutboundMessage(channel="cli", chat_id="direct", content="noop"),
    )
    result = await bot.run("hi")
    assert result.tools_used == []
    assert result.messages == []


@pytest.mark.asyncio
async def test_run_user_hooks_still_fire_alongside_capture(tmp_path):
    """Capture hook must not displace user-provided hooks."""
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    seen_iterations: list[int] = []

    class UserHook(AgentHook):
        async def after_iteration(self, context: AgentHookContext) -> None:
            seen_iterations.append(context.iteration)

    async def fake_process_direct(message, *, session_key):
        extras = bot._loop._extra_hooks
        assert len(extras) == 2, f"expected capture + user hook, got {len(extras)}"
        ctx = AgentHookContext(iteration=7, messages=[])
        for h in extras:
            await h.after_iteration(ctx)
        return OutboundMessage(channel="cli", chat_id="direct", content="ok")

    bot._loop.process_direct = fake_process_direct
    await bot.run("x", hooks=[UserHook()])
    assert seen_iterations == [7]


@pytest.mark.asyncio
async def test_run_restores_extra_hooks_even_on_populated_iterations(tmp_path):
    """Previously-installed _extra_hooks must be restored regardless of capture state."""
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    sentinel_hook = AgentHook()
    bot._loop._extra_hooks = [sentinel_hook]

    async def fake_process_direct(message, *, session_key):
        ctx = AgentHookContext(iteration=0, messages=[])
        for h in bot._loop._extra_hooks:
            await h.after_iteration(ctx)
        return OutboundMessage(channel="cli", chat_id="direct", content="done")

    bot._loop.process_direct = fake_process_direct
    await bot.run("hello")
    assert bot._loop._extra_hooks == [sentinel_hook]
