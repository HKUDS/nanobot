"""Tests for sustained goal tools (`long_task`, `complete_goal`)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.long_task import (
    CompleteGoalTool,
    LongTaskTool,
)
from nanobot.bus.outbound_events import GoalStateSyncEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventBus
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import WebuiTurnCoordinator


def _tools(sm: SessionManager) -> tuple[LongTaskTool, CompleteGoalTool]:
    lt = LongTaskTool(sessions=sm)
    cg = CompleteGoalTool(sessions=sm)
    return lt, cg


def _request_context(chat_id: str = "c1") -> RequestContext:
    return RequestContext(
        channel="websocket",
        chat_id=chat_id,
        session_key=f"websocket:{chat_id}",
        metadata={},
    )


@pytest.mark.asyncio
async def test_long_task_records_goal_metadata(tmp_path):
    sm = SessionManager(tmp_path)
    lt, _cg = _tools(sm)

    with request_context(_request_context()):
        out = await lt.execute(goal="Do the thing", ui_summary="thing")
    assert "Goal recorded" in out

    sess = sm.get_or_create("websocket:c1")
    blob = sess.metadata.get(GOAL_STATE_KEY)
    assert isinstance(blob, dict)
    assert blob["status"] == "active"
    assert blob["objective"] == "Do the thing"
    assert blob["ui_summary"] == "thing"


@pytest.mark.asyncio
async def test_long_task_rejects_second_active_goal(tmp_path):
    sm = SessionManager(tmp_path)
    lt, _cg = _tools(sm)

    with request_context(_request_context()):
        await lt.execute(goal="First")
        out = await lt.execute(goal="Second")
    assert "already active" in out


@pytest.mark.asyncio
async def test_complete_goal_closes_active_goal(tmp_path):
    sm = SessionManager(tmp_path)
    lt, cg = _tools(sm)

    with request_context(_request_context()):
        await lt.execute(goal="X")
        out = await cg.execute(recap="Done.")
    assert "marked complete" in out

    sess = sm.get_or_create("websocket:c1")
    blob = sess.metadata.get(GOAL_STATE_KEY)
    assert blob["status"] == "completed"
    assert blob["recap"] == "Done."


@pytest.mark.asyncio
async def test_goal_tools_keep_request_context_per_task(tmp_path):
    sm = SessionManager(tmp_path)
    lt = LongTaskTool(sessions=sm)
    cg = CompleteGoalTool(sessions=sm)
    ctx_a = RequestContext(channel="websocket", chat_id="a", session_key="websocket:a")
    ctx_b = RequestContext(channel="websocket", chat_id="b", session_key="websocket:b")

    async def start_goal(ctx: RequestContext, goal: str) -> str:
        with request_context(ctx):
            return await lt.execute(goal=goal)

    task_a = asyncio.create_task(start_goal(ctx_a, "Goal A"))
    task_b = asyncio.create_task(start_goal(ctx_b, "Goal B"))
    await asyncio.gather(task_a, task_b)

    assert sm.get_or_create("websocket:a").metadata[GOAL_STATE_KEY]["objective"] == "Goal A"
    assert sm.get_or_create("websocket:b").metadata[GOAL_STATE_KEY]["objective"] == "Goal B"

    async def complete_goal(ctx: RequestContext, recap: str) -> str:
        with request_context(ctx):
            return await cg.execute(recap=recap)

    done_a = asyncio.create_task(complete_goal(ctx_a, "Done A"))
    done_b = asyncio.create_task(complete_goal(ctx_b, "Done B"))
    await asyncio.gather(done_a, done_b)

    assert sm.get_or_create("websocket:a").metadata[GOAL_STATE_KEY]["recap"] == "Done A"
    assert sm.get_or_create("websocket:b").metadata[GOAL_STATE_KEY]["recap"] == "Done B"


@pytest.mark.asyncio
async def test_goal_tools_share_authoritative_request_context(tmp_path):
    """Both goal tools resolve routing from the same request snapshot."""
    sm = SessionManager(tmp_path)
    lt = LongTaskTool(sessions=sm)
    cg = CompleteGoalTool(sessions=sm)
    ctx = RequestContext(channel="websocket", chat_id="a", session_key="websocket:a")

    with request_context(ctx):
        assert lt._session() is sm.get_or_create("websocket:a")
        assert cg._session() is sm.get_or_create("websocket:a")

    assert lt._session() is None
    assert cg._session() is None


@pytest.mark.asyncio
async def test_long_task_publishes_goal_state_ws_after_save(tmp_path):
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    runtime_events = RuntimeEventBus()
    sm = SessionManager(tmp_path)
    WebuiTurnCoordinator(
        bus=bus,
        sessions=sm,
        schedule_background=lambda _coro: None,
    ).subscribe(runtime_events)
    lt = LongTaskTool(sessions=sm, runtime_events=runtime_events)
    rc = RequestContext(
        channel="websocket",
        chat_id="chat-99",
        session_key="websocket:chat-99",
        metadata={},
    )
    with request_context(rc):
        await lt.execute(goal="Objective alpha", ui_summary="alpha")

    bus.publish_outbound.assert_awaited_once()
    call = bus.publish_outbound.await_args.args[0]
    assert call.channel == "websocket"
    assert call.chat_id == "chat-99"
    assert isinstance(call.event, GoalStateSyncEvent)
    assert call.event.goal_state == {
        "active": True,
        "ui_summary": "alpha",
        "objective": "Objective alpha",
    }


@pytest.mark.asyncio
async def test_complete_goal_publishes_inactive_goal_state_ws(tmp_path):
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    runtime_events = RuntimeEventBus()
    sm = SessionManager(tmp_path)
    WebuiTurnCoordinator(
        bus=bus,
        sessions=sm,
        schedule_background=lambda _coro: None,
    ).subscribe(runtime_events)
    lt = LongTaskTool(sessions=sm, runtime_events=runtime_events)
    cg = CompleteGoalTool(sessions=sm, runtime_events=runtime_events)
    rc = RequestContext(
        channel="websocket",
        chat_id="chat-z",
        session_key="websocket:chat-z",
        metadata={},
    )
    with request_context(rc):
        await lt.execute(goal="X")

        bus.publish_outbound.reset_mock()
        await cg.execute(recap="Done.")

    bus.publish_outbound.assert_awaited_once()
    call = bus.publish_outbound.await_args.args[0]
    assert isinstance(call.event, GoalStateSyncEvent)
    assert call.event.goal_state == {"active": False}


@pytest.mark.asyncio
async def test_complete_goal_without_active_is_noop_message(tmp_path):
    sm = SessionManager(tmp_path)
    _lt, cg = _tools(sm)

    with request_context(_request_context()):
        out = await cg.execute(recap="n/a")
    assert "No active" in out


@pytest.mark.asyncio
async def test_long_task_skips_ws_publish_without_bus(tmp_path):
    sm = SessionManager(tmp_path)
    lt, _cg = _tools(sm)
    with request_context(_request_context()):
        out = await lt.execute(goal="Solo", ui_summary="s")
    assert "Goal recorded" in out


@pytest.mark.asyncio
async def test_long_task_and_complete_goal_registered(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    lt = loop.tools.get("long_task")
    cg = loop.tools.get("complete_goal")
    assert lt is not None and lt.name == "long_task"
    assert cg is not None and cg.name == "complete_goal"
