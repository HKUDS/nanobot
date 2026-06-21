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
         patch("nanobot.providers.factory.make_provider") as mock_prov:
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
    # Hooks are passed per-call via extra_hooks (not by mutating shared loop state).
    from nanobot.agent.hook import SDKCaptureHook

    bot._loop.process_direct.assert_awaited_once()
    call = bot._loop.process_direct.await_args
    assert call.args == ("hi",)
    assert call.kwargs["session_key"] == "sdk:default"
    assert any(isinstance(h, SDKCaptureHook) for h in call.kwargs["extra_hooks"])


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
    from nanobot.providers.factory import make_provider

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
        provider = make_provider(config)

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
    bot._loop.process_direct.assert_awaited_once()
    assert bot._loop.process_direct.await_args.args == ("hi",)
    assert bot._loop.process_direct.await_args.kwargs["session_key"] == "user-alice"


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

    async def fake_process_direct(message, *, session_key, extra_hooks):
        # Hooks now arrive per-call via extra_hooks, not via shared loop state.
        extras = extra_hooks
        messages = [{"role": "user", "content": message}]
        ctx1 = AgentHookContext(iteration=0, messages=messages)
        ctx1.tool_calls = [
            ToolCallRequest(id="c1", name="read_file", arguments={}),
            ToolCallRequest(id="c2", name="grep", arguments={}),
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
    assert result.tools_used == ["read_file", "grep", "web_fetch"]


@pytest.mark.asyncio
async def test_run_populates_final_messages(tmp_path):
    """messages reflects the agent's message list at the last iteration."""
    from nanobot.agent.hook import AgentHookContext
    from nanobot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    async def fake_process_direct(message, *, session_key, extra_hooks):
        extras = extra_hooks
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

    async def fake_process_direct(message, *, session_key, extra_hooks):
        extras = extra_hooks
        assert len(extras) == 2, f"expected capture + user hook, got {len(extras)}"
        ctx = AgentHookContext(iteration=7, messages=[])
        for h in extras:
            await h.after_iteration(ctx)
        return OutboundMessage(channel="cli", chat_id="direct", content="ok")

    bot._loop.process_direct = fake_process_direct
    await bot.run("x", hooks=[UserHook()])
    assert seen_iterations == [7]


@pytest.mark.asyncio
async def test_run_uses_loop_configured_hooks_as_base_without_mutating(tmp_path):
    """The loop's configured _extra_hooks are used as the base for a run and are
    never mutated by run() (so they cannot leak/clobber across calls)."""
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.bus.events import OutboundMessage

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    sentinel_hook = AgentHook()
    bot._loop._extra_hooks = [sentinel_hook]

    received: list[AgentHook] = []

    async def fake_process_direct(message, *, session_key, extra_hooks):
        received.extend(extra_hooks)
        ctx = AgentHookContext(iteration=0, messages=[])
        for h in extra_hooks:
            await h.after_iteration(ctx)
        return OutboundMessage(channel="cli", chat_id="direct", content="done")

    bot._loop.process_direct = fake_process_direct
    await bot.run("hello")

    # Configured hook is carried into the run as the base (after the capture hook)...
    assert sentinel_hook in received
    # ...and the loop's own list is left untouched.
    assert bot._loop._extra_hooks == [sentinel_hook]


@pytest.mark.asyncio
async def test_concurrent_runs_do_not_clobber_each_others_hooks(tmp_path):
    """Regression for the per-run hook race: two concurrent run() calls on one
    Nanobot must each use only their own hooks and capture only their own tools.

    The fix passes hooks as a ``process_direct(extra_hooks=...)`` argument instead
    of mutating the shared ``loop._extra_hooks``; this test interleaves two runs so
    that the old shared-state approach would have clobbered one run's hooks.
    """
    import asyncio

    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.bus.events import OutboundMessage
    from nanobot.providers.base import ToolCallRequest

    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)

    seen: dict[str, list[int]] = {}

    class TaggedHook(AgentHook):
        def __init__(self, tag: str) -> None:
            super().__init__()
            self.tag = tag

        async def after_iteration(self, context: AgentHookContext) -> None:
            seen.setdefault(self.tag, []).append(context.iteration)

    a_inflight = asyncio.Event()
    a_may_finish = asyncio.Event()

    async def fake_process_direct(message, *, session_key, extra_hooks):
        ctx = AgentHookContext(
            iteration=0, messages=[{"role": "user", "content": message}]
        )
        ctx.tool_calls = [ToolCallRequest(id=message, name=f"tool_{message}", arguments={})]
        if message == "A":
            # Hold A open while B runs to completion, so any shared hook state
            # would be overwritten by B before A fires its hooks.
            a_inflight.set()
            await a_may_finish.wait()
        for h in extra_hooks:
            await h.after_iteration(ctx)
        return OutboundMessage(channel="cli", chat_id="direct", content=message)

    bot._loop.process_direct = fake_process_direct

    async def run_b():
        await a_inflight.wait()
        res = await bot.run("B", session_key="s-b", hooks=[TaggedHook("B")])
        a_may_finish.set()
        return res

    res_a, res_b = await asyncio.gather(
        bot.run("A", session_key="s-a", hooks=[TaggedHook("A")]),
        run_b(),
    )

    # Each run captured only its own tool, and each tagged hook fired only once:
    # no cross-run bleed despite the interleaving.
    assert res_a.tools_used == ["tool_A"]
    assert res_b.tools_used == ["tool_B"]
    assert seen == {"A": [0], "B": [0]}


@pytest.mark.asyncio
async def test_sdk_capture_prefers_run_level_snapshot():
    from nanobot.agent.hook import AgentHookContext, AgentRunHookContext, SDKCaptureHook
    from nanobot.providers.base import ToolCallRequest

    hook = SDKCaptureHook()
    iter_messages = [{"role": "user", "content": "work"}]
    iter_context = AgentHookContext(iteration=0, messages=iter_messages)
    iter_context.tool_calls = [
        ToolCallRequest(id="call_1", name="read_file", arguments={}),
        ToolCallRequest(id="call_2", name="grep", arguments={}),
    ]
    await hook.after_iteration(iter_context)

    final_messages = [
        {"role": "user", "content": "work"},
        {"role": "assistant", "content": "done"},
    ]
    await hook.after_run(AgentRunHookContext(
        messages=final_messages,
        tools_used=["read_file"],
    ))

    assert hook.tools_used == ["read_file"]
    assert hook.messages == final_messages


@pytest.mark.asyncio
async def test_aclose_delegates_to_loop_close_mcp(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)
    bot._loop.close_mcp = AsyncMock()

    await bot.aclose()

    bot._loop.close_mcp.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_manager_calls_aclose_on_exit(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)
    bot._loop.close_mcp = AsyncMock()

    async with bot as b:
        assert b is bot

    bot._loop.close_mcp.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_manager_does_not_swallow_exceptions(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Nanobot.from_config(config_path, workspace=tmp_path)
    bot._loop.close_mcp = AsyncMock()

    with pytest.raises(ValueError):
        async with bot as b:
            assert b is bot
            raise ValueError("boom")

    bot._loop.close_mcp.assert_awaited_once()
