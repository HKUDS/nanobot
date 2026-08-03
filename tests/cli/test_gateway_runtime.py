"""Regression tests for gateway runtime resource teardown on stop.

Covers the lifecycle contract of ``_close_gateway_runtime``: runtime tasks
(including the agent loop and in-flight turns) are cancelled and awaited --
bounded -- before exec sessions, subagents, and MCP servers are closed, the
close is deterministic and idempotent, and a stuck or failing cleanup cannot
block the stop.
"""

import asyncio
import time

from nanobot.cli.gateway_runtime import _close_gateway_runtime


class _FakeAgent:
    def __init__(self, events: list[str] | None = None) -> None:
        self.close_calls = 0
        self.events = events if events is not None else []
        self.hang_on_close = False
        self.raise_on_close = False
        self.background: asyncio.Task[None] | None = None

    async def close_mcp(self) -> None:
        self.close_calls += 1
        if self.hang_on_close:
            await asyncio.sleep(3600)
        if self.raise_on_close:
            raise RuntimeError("cleanup exploded")
        if self.background is not None:
            await self.background
        self.events.append("close_mcp")


class _FakeChannels:
    def __init__(self) -> None:
        self.stopped = 0
        self.events: list[str] = []

    async def stop_all(self) -> None:
        self.stopped += 1
        self.events.append("channels_stopped")


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
    channels = _FakeChannels()
    task = asyncio.create_task(_cancellable_task(events))
    await asyncio.sleep(0)  # let the task start (cancellation pre-start skips its body)

    await _close_gateway_runtime(agent, channels, [task], None, False)

    assert events == ["cancelled", "close_mcp"]  # cancel happens before close
    assert channels.stopped == 1
    assert agent.close_calls == 1
    assert task.cancelled()


async def test_pending_background_work_is_drained_before_close_returns() -> None:
    agent = _FakeAgent()
    channels = _FakeChannels()
    done: dict[str, bool] = {"done": False}

    async def background_work() -> None:
        await asyncio.sleep(0.01)
        done["done"] = True

    agent.background = asyncio.create_task(background_work())

    await _close_gateway_runtime(agent, channels, [], None, False)

    assert done["done"] is True
    assert agent.close_calls == 1


async def test_stubborn_task_does_not_block_past_wait_timeout() -> None:
    agent = _FakeAgent()
    channels = _FakeChannels()
    events: list[str] = []
    task = asyncio.create_task(_stubborn_task(events))
    await asyncio.sleep(0)  # let the task start (cancellation pre-start skips its body)

    start = time.monotonic()
    await _close_gateway_runtime(
        agent,
        channels,
        [task],
        None,
        False,
        task_wait_timeout=0.05,
    )
    elapsed = time.monotonic() - start
    for _ in range(10):
        await asyncio.sleep(0)  # let the swallowed cancellation handler run

    assert "swallowed" in events  # task was cancelled, then refused to die
    assert not task.done()  # still running despite cancellation
    assert agent.close_calls == 1  # resources still closed underneath it
    assert elapsed < 1.0  # bounded, not held open by the stubborn task


async def test_hanging_close_is_bounded_and_does_not_raise() -> None:
    agent = _FakeAgent()
    agent.hang_on_close = True
    channels = _FakeChannels()

    start = time.monotonic()
    await _close_gateway_runtime(agent, channels, [], None, False, close_timeout=0.05)
    elapsed = time.monotonic() - start

    assert agent.close_calls == 1
    assert channels.stopped == 1
    assert elapsed < 1.0


async def test_failing_close_is_logged_but_shutdown_proceeds() -> None:
    agent = _FakeAgent()
    agent.raise_on_close = True
    channels = _FakeChannels()

    await _close_gateway_runtime(agent, channels, [], None, False)

    assert agent.close_calls == 1
    assert channels.stopped == 1  # teardown continued past the failure


async def test_duplicate_cleanup_is_idempotent() -> None:
    agent = _FakeAgent()
    channels = _FakeChannels()
    task = asyncio.create_task(_cancellable_task([]))

    await _close_gateway_runtime(agent, channels, [task], None, False)
    await _close_gateway_runtime(agent, channels, [task], None, False)

    assert agent.close_calls == 2  # second pass is a clean no-op
    assert channels.stopped == 2
    assert task.cancelled()


async def test_runtime_tasks_gather_is_awaited_when_not_drained() -> None:
    agent = _FakeAgent()
    channels = _FakeChannels()
    runtime_tasks = asyncio.gather(asyncio.sleep(0))

    await _close_gateway_runtime(agent, channels, [], runtime_tasks, False)

    assert runtime_tasks.done()
    assert agent.close_calls == 1


async def test_cancelled_runtime_tasks_gather_does_not_raise() -> None:
    agent = _FakeAgent()
    channels = _FakeChannels()
    runtime_tasks = asyncio.gather(asyncio.sleep(3600))
    runtime_tasks.cancel()

    await _close_gateway_runtime(agent, channels, [], runtime_tasks, False)

    assert runtime_tasks.done()  # the cancelled gather was awaited without raising
    assert agent.close_calls == 1
