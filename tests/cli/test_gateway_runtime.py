"""Regression tests for gateway runtime resource teardown on stop.

Covers the lifecycle contract of ``_close_gateway_runtime``: runtime tasks
(including the agent loop and in-flight turns) are cancelled and awaited --
bounded -- before exec sessions, subagents, and MCP servers are closed, the
close is deterministic and idempotent, and a stuck or failing cleanup cannot
block the stop.
"""

import asyncio
import time
from contextlib import suppress

from nanobot.agent.hook import AgentRunHookContext
from nanobot.agent.tools.mcp import MCPProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.cli.gateway_runtime import (
    _close_gateway_runtime,
    _gateway_readiness_payload,
    _MCPReadinessHook,
)


class _FakeAgent:
    def __init__(self, events: list[str] | None = None) -> None:
        self.close_calls = 0
        self.events = events if events is not None else []
        self.hang_on_close = False
        self.raise_on_close = False
        self.background: asyncio.Task[None] | None = None

    async def aclose(self) -> None:
        self.close_calls += 1
        if self.hang_on_close:
            await asyncio.sleep(3600)
        if self.raise_on_close:
            raise RuntimeError("cleanup exploded")
        if self.background is not None:
            await self.background
        self.events.append("aclose")


class _FakeChannels:
    def __init__(self) -> None:
        self.stopped = 0
        self.events: list[str] = []

    async def stop_all(self) -> None:
        self.stopped += 1
        self.events.append("channels_stopped")


class _FakeMCPProvider:
    def __init__(self, events: list[str] | None = None) -> None:
        self.close_calls = 0
        self.events = events if events is not None else []

    async def aclose(self) -> None:
        self.close_calls += 1
        self.events.append("mcp_closed")


class _TrackingMCPProvider(MCPProvider):
    def __init__(self) -> None:
        super().__init__({}, ToolRegistry())
        self.connect_calls = 0

    async def connect(self) -> None:
        self.connect_calls += 1


def test_gateway_readiness_is_degraded_when_required_websocket_is_unavailable() -> None:
    channels = type(
        "Channels",
        (),
        {
            "enabled_channels": ["websocket"],
            "get_status": lambda self: {
                "websocket": {
                    "enabled": True,
                    "running": False,
                    "state": "starting",
                }
            },
        },
    )()

    ready, payload = _gateway_readiness_payload(channels)

    assert ready is False
    assert payload == {
        "status": "degraded",
        "process": "alive",
        "ready": False,
        "websocket": "starting",
    }


async def test_mcp_readiness_hook_delegates_to_application_provider() -> None:
    provider = _TrackingMCPProvider()
    hook = _MCPReadinessHook(provider)

    await hook.before_run(AgentRunHookContext(messages=[]))

    assert provider.connect_calls == 1


async def _cancellable_task(events: list[str]) -> None:
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        events.append("cancelled")
        raise


async def _stubborn_task(events: list[str]) -> None:
    """Task that swallows cancellation and keeps running."""
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        events.append("swallowed")
        await asyncio.sleep(3600)


async def test_runtime_tasks_cancelled_before_resources_closed() -> None:
    events: list[str] = []
    agent = _FakeAgent(events)
    provider = _FakeMCPProvider(events)
    channels = _FakeChannels()
    task = asyncio.create_task(_cancellable_task(events))
    await asyncio.sleep(0)  # let the task start (cancellation pre-start skips its body)

    await _close_gateway_runtime(agent, provider, channels, [task], None)

    assert events == ["cancelled", "aclose", "mcp_closed"]
    assert channels.stopped == 1
    assert agent.close_calls == 1
    assert task.cancelled()


async def test_pending_background_work_is_drained_before_close_returns() -> None:
    agent = _FakeAgent()
    provider = _FakeMCPProvider()
    channels = _FakeChannels()
    done: dict[str, bool] = {"done": False}

    async def background_work() -> None:
        await asyncio.sleep(0.01)
        done["done"] = True

    agent.background = asyncio.create_task(background_work())

    await _close_gateway_runtime(agent, provider, channels, [], None)

    assert done["done"] is True
    assert agent.close_calls == 1


async def test_stubborn_task_does_not_block_past_wait_timeout() -> None:
    agent = _FakeAgent()
    provider = _FakeMCPProvider()
    channels = _FakeChannels()
    events: list[str] = []
    task = asyncio.create_task(_stubborn_task(events))
    await asyncio.sleep(0)  # let the task start (cancellation pre-start skips its body)
    runtime_tasks = asyncio.gather(task)

    start = time.monotonic()
    await _close_gateway_runtime(
        agent,
        provider,
        channels,
        [task],
        runtime_tasks,
        task_wait_timeout=0.05,
    )
    elapsed = time.monotonic() - start
    for _ in range(10):
        await asyncio.sleep(0)  # let the swallowed cancellation handler run

    assert "swallowed" in events  # task was cancelled, then refused to die
    assert task.done()  # the timed-out task received a second cancellation
    assert runtime_tasks.done()
    assert agent.close_calls == 1  # resources still closed underneath it
    assert provider.close_calls == 1
    assert elapsed < 1.0  # bounded, not held open by the stubborn task


async def test_hanging_close_is_bounded_and_does_not_raise() -> None:
    agent = _FakeAgent()
    provider = _FakeMCPProvider()
    agent.hang_on_close = True
    channels = _FakeChannels()

    start = time.monotonic()
    await _close_gateway_runtime(
        agent,
        provider,
        channels,
        [],
        None,
        close_timeout=0.05,
    )
    elapsed = time.monotonic() - start

    assert agent.close_calls == 1
    assert provider.close_calls == 1
    assert channels.stopped == 1
    assert elapsed < 1.0


async def test_failing_close_is_logged_but_shutdown_proceeds() -> None:
    agent = _FakeAgent()
    provider = _FakeMCPProvider()
    agent.raise_on_close = True
    channels = _FakeChannels()

    await _close_gateway_runtime(agent, provider, channels, [], None)

    assert agent.close_calls == 1
    assert provider.close_calls == 1
    assert channels.stopped == 1  # teardown continued past the failure


async def test_duplicate_cleanup_is_idempotent() -> None:
    agent = _FakeAgent()
    provider = _FakeMCPProvider()
    channels = _FakeChannels()
    task = asyncio.create_task(_cancellable_task([]))

    await _close_gateway_runtime(agent, provider, channels, [task], None)
    await _close_gateway_runtime(agent, provider, channels, [task], None)

    assert agent.close_calls == 2  # second pass is a clean no-op
    assert provider.close_calls == 2
    assert channels.stopped == 2
    assert task.cancelled()


async def test_finished_runtime_tasks_gather_is_retrieved() -> None:
    agent = _FakeAgent()
    provider = _FakeMCPProvider()
    channels = _FakeChannels()
    finished = asyncio.get_running_loop().create_future()
    finished.set_result(None)
    runtime_tasks = asyncio.gather(finished)
    await asyncio.sleep(0)  # let the gather observe the finished child

    await _close_gateway_runtime(agent, provider, channels, [], runtime_tasks)

    assert runtime_tasks.done()
    assert agent.close_calls == 1
    assert provider.close_calls == 1


async def test_cancelled_runtime_tasks_gather_does_not_raise() -> None:
    agent = _FakeAgent()
    provider = _FakeMCPProvider()
    channels = _FakeChannels()
    runtime_tasks = asyncio.gather(asyncio.sleep(3600))
    runtime_tasks.cancel()

    await _close_gateway_runtime(agent, provider, channels, [], runtime_tasks)
    with suppress(asyncio.CancelledError):
        await runtime_tasks  # settle the cancelled gather without raising

    assert runtime_tasks.done()  # the cancelled gather was awaited without raising
    assert agent.close_calls == 1
    assert provider.close_calls == 1


def test_restart_commits_after_reply_then_tears_down_and_releases_all_owners(monkeypatch, tmp_path):
    from contextlib import contextmanager, nullcontext
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import pytest

    from nanobot.cli import gateway_runtime as gateway
    from nanobot.config.schema import Config
    from nanobot.gateway.runtime import GatewayInstance, GatewayRuntimePaths
    from nanobot.utils.restart import ProcessRestart

    events = []
    callbacks = {}
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.agents.defaults.dream.enabled = True
    config.gateway.heartbeat.enabled = False
    config.gateway.restart_mode = "spawn"
    paths = GatewayRuntimePaths.for_instance(data_dir=tmp_path)
    instance = GatewayInstance(config_path=tmp_path / "config.json", workspace=None, paths=paths)

    @contextmanager
    def owner(label):
        events.append(f"{label} acquired")
        try:
            yield SimpleNamespace(health_identity=object())
        finally:
            events.append(f"{label} released")

    runtime = MagicMock(paths=paths)
    runtime.foreground_instance.side_effect = lambda _options: owner("claim")
    runtime.wait_for_shutdown_request = AsyncMock()
    runtime.status.return_value = SimpleNamespace(launch_mode="foreground", lifetime="explicit")
    monkeypatch.setattr(gateway, "GatewayRuntime", lambda **_kwargs: runtime)
    monkeypatch.setattr(gateway, "installation_access", lambda **_kwargs: owner("installation"))
    monkeypatch.setattr("nanobot.update_profiles.record_gateway_profile", lambda *_args, **_kwargs: owner("profile"))
    monkeypatch.setattr(gateway, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(gateway, "_tcp_endpoint_reachable", lambda *_args: False)
    monkeypatch.setattr(gateway, "_webui_channel_enabled", lambda *_args: False)
    monkeypatch.setattr(gateway, "warmup_token_encoding", lambda: None)
    monkeypatch.setattr(gateway, "_prepare_webui_bundle_for_gateway", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gateway, "sync_workspace_templates", lambda *_args: None)
    monkeypatch.setattr(gateway, "register_image_generation_tool", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gateway.cli_terminal, "_ensure_interactive_tty_mode", lambda: None)
    monkeypatch.setattr(gateway, "_install_gateway_shutdown_handlers", lambda *_args: lambda: None)
    snapshot = SimpleNamespace(provider=MagicMock(), model="test", context_window_tokens=1000, signature=())
    monkeypatch.setattr("nanobot.providers.factory.build_provider_snapshot", lambda _config: snapshot)
    monkeypatch.setattr("nanobot.session.manager.SessionManager", MagicMock())
    monkeypatch.setattr("nanobot.webui.recovery.RecoveryCoordinator", MagicMock(return_value=MagicMock(scan=AsyncMock())))
    monkeypatch.setattr("nanobot.session.webui_turns.WebuiTurnCoordinator", MagicMock(return_value=SimpleNamespace(connected=nullcontext)))

    async def wait_forever(*_args, **_kwargs):
        await asyncio.Event().wait()

    agent = MagicMock()
    agent.model = "test"
    agent.tools = ToolRegistry()
    agent.subagents.recover_interrupted = AsyncMock()
    agent.run = wait_forever
    agent.aclose = AsyncMock(side_effect=lambda: events.append("agent closed"))
    agent.preserve_inflight_turns_on_shutdown.side_effect = lambda: events.append("checkpoints preserved")
    agent.stop.side_effect = lambda: events.append("agent stopped")

    def make_agent(_config, _bus, **kwargs):
        callbacks["agent"] = kwargs["restart_request"]
        return agent

    monkeypatch.setattr(gateway, "AgentLoop", SimpleNamespace(from_config=make_agent))
    provider = MagicMock(connect=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr(gateway, "MCPProvider", SimpleNamespace(from_config=lambda *_args: provider))
    cron = MagicMock(start=AsyncMock())
    cron.status.return_value = {"jobs": 0}
    cron.stop.side_effect = lambda: events.append("cron stopped")
    monkeypatch.setattr("nanobot.cron.service.CronService", lambda *_args, **_kwargs: cron)
    monkeypatch.setattr("nanobot.triggers.local_runner.run_local_trigger_queue", wait_forever)
    monkeypatch.setattr("nanobot.config.watcher.watch_config_file", wait_forever)

    async def channel_start():
        assert callbacks["agent"] == callbacks["webui"]
        ticket = callbacks["webui"]()
        assert ticket is not None
        events.append("accepted reply drained")
        assert "cron stopped" not in events
        ticket.commit()
        await wait_forever()

    channels = MagicMock(enabled_channels=[])
    channels.start_all = channel_start
    channels.stop_all = AsyncMock(side_effect=lambda: events.append("channels stopped"))

    def make_channels(_config, _bus, **kwargs):
        callbacks["webui"] = kwargs["webui_restart"]
        assert kwargs["webui_model_runtime"] is agent.runtime_resolver
        return channels

    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", make_channels)
    monkeypatch.setattr("nanobot.gateway.restart.GatewayRestartPlan.execute", lambda _self: events.append("replacement"))

    with pytest.raises(ProcessRestart) as raised:
        with owner("outer entry installation"):
            gateway._run_gateway(config, gateway_instance=instance, health_server_enabled=False)

    assert events == [
        "outer entry installation acquired", "installation acquired", "claim acquired", "profile acquired",
        "accepted reply drained", "cron stopped", "checkpoints preserved", "agent stopped",
        "channels stopped", "agent closed", "profile released", "claim released", "installation released",
        "outer entry installation released",
    ]
    raised.value.execute()
    assert events[-1] == "replacement"
    assert provider.aclose.await_count == 2
