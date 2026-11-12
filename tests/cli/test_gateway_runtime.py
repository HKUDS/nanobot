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
