from __future__ import annotations

import asyncio
from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.hook import AgentHookContext
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.execution import execute_tool_calls
from nanobot.events import EventSink, ModelRequestEvent
from nanobot.providers.base import LLMResponse, LLMUsage, ToolCallRequest


def spec(provider, sink, **kwargs):
    tools = MagicMock()
    tools.get_definitions.return_value = []
    return make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools, model="test-model", max_iterations=2,
        max_tool_result_chars=10000, events=sink, **kwargs,
    )


@pytest.mark.asyncio
async def test_requests_arrive_before_runner_finishes_and_cancel_is_terminal():
    events = []
    entered = asyncio.Event()
    block = asyncio.Event()

    async def publish(event):
        events.append(event)

    async def provider_call(**kwargs):
        entered.set()
        await block.wait()
        return LLMResponse(content="done")

    provider = MagicMock()
    provider.chat_stream_with_retry = provider_call
    task = asyncio.create_task(AgentRunner().run(spec(provider, EventSink(publish))))
    await asyncio.wait_for(entered.wait(), 2)
    assert not task.done()
    assert [e.phase for e in events if isinstance(e, ModelRequestEvent)] == ["started"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    requests = [e for e in events if isinstance(e, ModelRequestEvent)]
    assert [e.phase for e in requests] == ["started", "cancelled"]
    assert requests[0].request_id == requests[1].request_id
    assert [e.sequence for e in requests] == [1, 2]
    assert requests[1].usage is None


@pytest.mark.asyncio
async def test_completed_request_usage_is_visible_while_tool_is_blocked():
    events = []
    entered = asyncio.Event()
    release = asyncio.Event()
    usage = LLMUsage.reported(input_tokens=12, output_tokens=3)

    async def publish(event):
        events.append(event)

    async def tool_call(*args):
        entered.set()
        await release.wait()
        return "ok"

    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest("c", "tool", {})], usage=usage),
        LLMResponse(content="done", usage=usage),
    ])
    run_spec = spec(provider, EventSink(publish))
    run_spec.tools.prepare_call.return_value = (None, {}, None)
    run_spec.tools.execute = tool_call
    task = asyncio.create_task(AgentRunner().run(run_spec))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert not task.done()
        requests = [e for e in events if isinstance(e, ModelRequestEvent)]
        assert [e.phase for e in requests] == ["started", "completed"]
        assert requests[-1].usage == usage
        assert requests[-1].round_usages == (usage,)
    finally:
        release.set()
        await task
    requests = [e for e in events if isinstance(e, ModelRequestEvent)]
    assert [e.sequence for e in requests] == [1, 2, 3, 4]
    assert len({e.run_id for e in requests}) == 1
    assert requests[0].request_id != requests[2].request_id
    assert requests[-1].usage == usage + usage


@pytest.mark.asyncio
async def test_live_round_usage_folds_recovery_before_tool_finishes():
    events = []
    entered = asyncio.Event()
    release = asyncio.Event()
    usages = [LLMUsage.reported(input_tokens=value, output_tokens=1) for value in (10, 20, 30)]

    async def publish(event):
        if isinstance(event, ModelRequestEvent):
            events.append(event)

    async def tool_call(*args):
        entered.set()
        await release.wait()
        return "ok"

    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest("bad", "", {})],
                    finish_reason="tool_calls", usage=usages[0]),
        LLMResponse(content=None, tool_calls=[ToolCallRequest("c", "tool", {})],
                    finish_reason="tool_calls", usage=usages[1]),
        LLMResponse(content="done", usage=usages[2]),
    ])
    run_spec = spec(provider, EventSink(publish))
    run_spec.tools.prepare_call.return_value = (None, {}, None)
    run_spec.tools.execute = tool_call
    task = asyncio.create_task(AgentRunner().run(run_spec))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert not task.done()
        completed = [event for event in events if event.phase == "completed"]
        assert completed[0].round_usages == (usages[0],)
        assert completed[-1].round_usages == (usages[0] + usages[1],)
        assert completed[-1].usage == usages[0] + usages[1]
    finally:
        release.set()
        result = await task
    assert events[-1].round_usages == tuple(result.round_usages)
    assert events[-1].usage == result.usage
    assert [usage.input_tokens for usage in result.round_usages] == [30, 30]


@pytest.mark.asyncio
async def test_individual_tool_finishes_before_blocked_sibling():
    emitted = []
    settled = []
    fast_finished = asyncio.Event()
    release = asyncio.Event()
    tools = MagicMock()
    tools.prepare_call.return_value = (None, {}, None)

    async def execute(name, args):
        if name == "slow":
            await release.wait()
        return name

    tools.execute = execute

    async def publish(event):
        emitted.extend(event.tool_events or [])
        if any(e["call_id"] == "fast" and e["phase"] == "end" for e in event.tool_events or []):
            fast_finished.set()

    task = asyncio.create_task(execute_tool_calls(
        tools, [ToolCallRequest("slow", "slow", {}), ToolCallRequest("fast", "fast", {})],
        concurrent=True, external_lookup_counts={}, workspace_violation_counts={},
        hook=AgentProgressHook(EventSink(publish)), context=AgentHookContext(0, []),
        on_settled=AsyncMock(side_effect=settled.extend),
    ))
    try:
        await asyncio.wait_for(fast_finished.wait(), 2)
        assert not task.done()
        assert not any(e["call_id"] == "slow" and e["phase"] == "end" for e in emitted)
    finally:
        release.set()
        await task
    assert [completed.result for completed in settled] == ["slow", "fast"]
    assert [(e["call_id"], e["phase"]) for e in emitted].count(("fast", "end")) == 1


@pytest.mark.asyncio
async def test_request_snapshots_bound_rounds_without_losing_cumulative_usage():
    events = []
    usage = LLMUsage.reported(input_tokens=12, output_tokens=3)

    async def publish(event):
        events.append(event)

    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        *[LLMResponse(content=None, tool_calls=[ToolCallRequest(str(i), "tool", {})], usage=usage)
          for i in range(9)],
        LLMResponse(content="done", usage=usage),
    ])
    run_spec = spec(provider, EventSink(publish))
    run_spec.max_iterations = 10
    run_spec.tools.prepare_call.return_value = (None, {}, None)
    run_spec.tools.execute = AsyncMock(return_value="ok")
    result = await AgentRunner().run(run_spec)
    completed = [e for e in events if isinstance(e, ModelRequestEvent) and e.phase == "completed"]
    assert len(completed) == 10
    assert len(completed[-1].round_usages) == 8
    assert completed[-1].usage == result.usage
    assert len(result.round_usages) == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [LLMResponse(content="error", finish_reason="error"), RuntimeError("failure")])
async def test_request_failure_has_one_terminal_event(response):
    events = []

    async def publish(event):
        events.append(event)

    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[response])
    expected = pytest.raises(RuntimeError, match="failure") if isinstance(response, RuntimeError) else nullcontext()
    with expected:
        await AgentRunner().run(spec(provider, EventSink(publish)))
    requests = [e for e in events if isinstance(e, ModelRequestEvent)]
    assert [e.phase for e in requests] == ["started", "failed"]
    assert requests[-1].usage is None


@pytest.mark.asyncio
async def test_tool_cancellation_closes_started_call_without_masking_cancel():
    emitted = []
    entered = asyncio.Event()
    tools = MagicMock()
    tools.prepare_call.return_value = (None, {}, None)

    async def execute(*args):
        entered.set()
        await asyncio.Event().wait()

    tools.execute = execute

    async def publish(event):
        emitted.extend(event.tool_events or [])
        if event.tool_events and event.tool_events[0]["phase"] == "error":
            raise RuntimeError("notification failure must not replace cancellation")

    task = asyncio.create_task(execute_tool_calls(
        tools, [ToolCallRequest("blocked", "blocked", {})], concurrent=False,
        external_lookup_counts={}, workspace_violation_counts={},
        hook=AgentProgressHook(EventSink(publish)), context=AgentHookContext(0, []),
    ))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [event["phase"] for event in emitted] == ["start", "error"]


def test_model_requests_are_optional_for_non_webui_channels():
    from nanobot.bus.notification_delivery import notification_is_deliverable

    for channel in ("telegram", "slack", "cli", "discord"):
        assert not notification_is_deliverable(ModelRequestEvent, channel=channel, publish_lifecycle=True)
    assert notification_is_deliverable(ModelRequestEvent, channel="websocket", publish_lifecycle=True)
