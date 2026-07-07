"""Tests for sustained goal tools (``create_goal``, ``update_goal``)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.goal import (
    CreateGoalTool,
    UpdateGoalTool,
)
from nanobot.bus.outbound_events import GoalStateSyncEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventBus
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import WebuiTurnCoordinator


def _goal_metadata() -> dict[str, object]:
    return {"original_command": "/goal", "goal_requested": True}


def _tools(
    sm: SessionManager,
    *,
    metadata: dict[str, object] | None = None,
) -> tuple[CreateGoalTool, UpdateGoalTool]:
    create = CreateGoalTool(sessions=sm)
    update = UpdateGoalTool(sessions=sm)
    rc = RequestContext(
        channel="websocket",
        chat_id="c1",
        session_key="websocket:c1",
        metadata=metadata if metadata is not None else _goal_metadata(),
    )
    create.set_context(rc)
    update.set_context(rc)
    return create, update


@pytest.mark.asyncio
async def test_create_goal_records_goal_metadata(tmp_path):
    sm = SessionManager(tmp_path)
    create, _update = _tools(sm)

    out = await create.execute(objective="Do the thing", ui_summary="thing")
    assert "Goal recorded" in out

    sess = sm.get_or_create("websocket:c1")
    blob = sess.metadata.get(GOAL_STATE_KEY)
    assert isinstance(blob, dict)
    assert blob["status"] == "active"
    assert blob["objective"] == "Do the thing"
    assert blob["ui_summary"] == "thing"


@pytest.mark.asyncio
async def test_create_goal_rejects_non_goal_turn(tmp_path):
    sm = SessionManager(tmp_path)
    create, _update = _tools(sm, metadata={})

    out = await create.execute(objective="Do the thing")

    assert "only allowed during an explicit /goal turn" in str(out)
    assert sm.get_or_create("websocket:c1").metadata.get(GOAL_STATE_KEY) is None


@pytest.mark.asyncio
async def test_create_goal_rejects_second_active_goal(tmp_path):
    sm = SessionManager(tmp_path)
    create, _update = _tools(sm)

    await create.execute(objective="First")
    out = await create.execute(objective="Second")
    assert "already active" in str(out)


@pytest.mark.asyncio
async def test_update_goal_complete_closes_active_goal(tmp_path):
    sm = SessionManager(tmp_path)
    create, update = _tools(sm)

    await create.execute(objective="X")
    update.set_context(RequestContext(channel="websocket", chat_id="c1", session_key="websocket:c1"))
    out = await update.execute(action="complete", recap="Done.")
    assert "marked complete" in out

    sess = sm.get_or_create("websocket:c1")
    blob = sess.metadata.get(GOAL_STATE_KEY)
    assert blob["status"] == "completed"
    assert blob["recap"] == "Done."


@pytest.mark.asyncio
async def test_update_goal_replace_keeps_goal_active_with_new_objective(tmp_path):
    sm = SessionManager(tmp_path)
    create, update = _tools(sm)

    await create.execute(objective="Old")
    update.set_context(RequestContext(channel="websocket", chat_id="c1", session_key="websocket:c1"))
    out = await update.execute(action="replace", objective="New", ui_summary="new")

    assert "Goal replaced" in out
    blob = sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]
    assert blob["status"] == "active"
    assert blob["objective"] == "New"
    assert blob["previous_objective"] == "Old"
    assert blob["ui_summary"] == "new"


@pytest.mark.asyncio
async def test_goal_tools_keep_request_context_per_task(tmp_path):
    sm = SessionManager(tmp_path)
    create = CreateGoalTool(sessions=sm)
    update = UpdateGoalTool(sessions=sm)
    ctx_a = RequestContext(
        channel="websocket",
        chat_id="a",
        session_key="websocket:a",
        metadata=_goal_metadata(),
    )
    ctx_b = RequestContext(
        channel="websocket",
        chat_id="b",
        session_key="websocket:b",
        metadata=_goal_metadata(),
    )

    create.set_context(ctx_a)
    task_a = asyncio.create_task(create.execute(objective="Goal A"))
    create.set_context(ctx_b)
    task_b = asyncio.create_task(create.execute(objective="Goal B"))
    await asyncio.gather(task_a, task_b)

    assert sm.get_or_create("websocket:a").metadata[GOAL_STATE_KEY]["objective"] == "Goal A"
    assert sm.get_or_create("websocket:b").metadata[GOAL_STATE_KEY]["objective"] == "Goal B"

    update.set_context(RequestContext(channel="websocket", chat_id="a", session_key="websocket:a"))
    done_a = asyncio.create_task(update.execute(action="complete", recap="Done A"))
    update.set_context(RequestContext(channel="websocket", chat_id="b", session_key="websocket:b"))
    done_b = asyncio.create_task(update.execute(action="complete", recap="Done B"))
    await asyncio.gather(done_a, done_b)

    assert sm.get_or_create("websocket:a").metadata[GOAL_STATE_KEY]["recap"] == "Done A"
    assert sm.get_or_create("websocket:b").metadata[GOAL_STATE_KEY]["recap"] == "Done B"


@pytest.mark.asyncio
async def test_goal_tools_context_isolated_across_tool_types(tmp_path):
    sm = SessionManager(tmp_path)
    create = CreateGoalTool(sessions=sm)
    update = UpdateGoalTool(sessions=sm)
    ctx = RequestContext(channel="websocket", chat_id="a", session_key="websocket:a")

    create.set_context(ctx)
    assert update._request_ctx.get() is None

    update.set_context(ctx)
    assert create._request_ctx.get() is ctx
    assert update._request_ctx.get() is ctx


@pytest.mark.asyncio
async def test_create_goal_publishes_goal_state_ws_after_save(tmp_path):
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    runtime_events = RuntimeEventBus()
    sm = SessionManager(tmp_path)
    WebuiTurnCoordinator(
        bus=bus,
        sessions=sm,
        schedule_background=lambda _coro: None,
    ).subscribe(runtime_events)
    create = CreateGoalTool(sessions=sm, runtime_events=runtime_events)
    rc = RequestContext(
        channel="websocket",
        chat_id="chat-99",
        session_key="websocket:chat-99",
        metadata=_goal_metadata(),
    )
    create.set_context(rc)

    await create.execute(objective="Objective alpha", ui_summary="alpha")

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
async def test_update_goal_publishes_inactive_goal_state_ws(tmp_path):
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    runtime_events = RuntimeEventBus()
    sm = SessionManager(tmp_path)
    WebuiTurnCoordinator(
        bus=bus,
        sessions=sm,
        schedule_background=lambda _coro: None,
    ).subscribe(runtime_events)
    create = CreateGoalTool(sessions=sm, runtime_events=runtime_events)
    update = UpdateGoalTool(sessions=sm, runtime_events=runtime_events)
    rc = RequestContext(
        channel="websocket",
        chat_id="chat-z",
        session_key="websocket:chat-z",
        metadata=_goal_metadata(),
    )
    create.set_context(rc)
    await create.execute(objective="X")

    bus.publish_outbound.reset_mock()
    update.set_context(
        RequestContext(channel="websocket", chat_id="chat-z", session_key="websocket:chat-z")
    )
    await update.execute(action="complete", recap="Done.")

    bus.publish_outbound.assert_awaited_once()
    call = bus.publish_outbound.await_args.args[0]
    assert isinstance(call.event, GoalStateSyncEvent)
    assert call.event.goal_state == {"active": False}


@pytest.mark.asyncio
async def test_update_goal_without_active_is_noop_message(tmp_path):
    sm = SessionManager(tmp_path)
    _create, update = _tools(sm)

    out = await update.execute(action="complete", recap="n/a")
    assert "No active" in out


@pytest.mark.asyncio
async def test_create_goal_skips_ws_publish_without_bus(tmp_path):
    sm = SessionManager(tmp_path)
    create, _update = _tools(sm)
    out = await create.execute(objective="Solo", ui_summary="s")
    assert "Goal recorded" in out


@pytest.mark.asyncio
async def test_goal_tools_registered_in_base_registry(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    create = loop.tools.get("create_goal")
    update = loop.tools.get("update_goal")
    assert create is not None and create.name == "create_goal"
    assert update is not None and update.name == "update_goal"
