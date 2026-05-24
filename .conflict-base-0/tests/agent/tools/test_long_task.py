"""Tests for sustained goal tools (`long_task`, `complete_goal`)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.long_task import (
    CompleteGoalTool,
    LongTaskTool,
)
from nanobot.bus.queue import MessageBus
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager


def _tools(sm: SessionManager) -> tuple[LongTaskTool, CompleteGoalTool]:
    lt = LongTaskTool(sessions=sm)
    cg = CompleteGoalTool(sessions=sm)
    rc = RequestContext(
        channel="websocket",
        chat_id="c1",
        session_key="websocket:c1",
        metadata={},
    )
    lt.set_context(rc)
    cg.set_context(rc)
    return lt, cg


@pytest.mark.asyncio
async def test_long_task_records_goal_metadata(tmp_path):
    sm = SessionManager(tmp_path)
    lt, _cg = _tools(sm)

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

    await lt.execute(goal="First")
    out = await lt.execute(goal="Second")
    assert "already active" in out


@pytest.mark.asyncio
async def test_complete_goal_closes_active_goal(tmp_path):
    sm = SessionManager(tmp_path)
    lt, cg = _tools(sm)

    await lt.execute(goal="X")
    out = await cg.execute(recap="Done.")
    assert "marked complete" in out

    sess = sm.get_or_create("websocket:c1")
    blob = sess.metadata.get(GOAL_STATE_KEY)
    assert blob["status"] == "completed"
    assert blob["recap"] == "Done."


@pytest.mark.asyncio
async def test_long_task_publishes_goal_state_ws_after_save(tmp_path):
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    sm = SessionManager(tmp_path)
    lt = LongTaskTool(sessions=sm, bus=bus)
    rc = RequestContext(
        channel="websocket",
        chat_id="chat-99",
        session_key="websocket:chat-99",
        metadata={},
    )
    lt.set_context(rc)

    await lt.execute(goal="Objective alpha", ui_summary="alpha")

    bus.publish_outbound.assert_awaited_once()
    call = bus.publish_outbound.await_args.args[0]
    assert call.channel == "websocket"
    assert call.chat_id == "chat-99"
    assert call.metadata.get("_goal_state_sync") is True
    assert call.metadata["goal_state"] == {
        "active": True,
        "ui_summary": "alpha",
        "objective": "Objective alpha",
    }


@pytest.mark.asyncio
async def test_complete_goal_publishes_inactive_goal_state_ws(tmp_path):
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    sm = SessionManager(tmp_path)
    lt = LongTaskTool(sessions=sm, bus=bus)
    cg = CompleteGoalTool(sessions=sm, bus=bus)
    rc = RequestContext(
        channel="websocket",
        chat_id="chat-z",
        session_key="websocket:chat-z",
        metadata={},
    )
    lt.set_context(rc)
    await lt.execute(goal="X")

    bus.publish_outbound.reset_mock()
    cg.set_context(rc)
    await cg.execute(recap="Done.")

    bus.publish_outbound.assert_awaited_once()
    call = bus.publish_outbound.await_args.args[0]
    assert call.metadata["goal_state"] == {"active": False}


@pytest.mark.asyncio
async def test_complete_goal_without_active_is_noop_message(tmp_path):
    sm = SessionManager(tmp_path)
    _lt, cg = _tools(sm)

    out = await cg.execute(recap="n/a")
    assert "No active" in out


@pytest.mark.asyncio
async def test_long_task_skips_ws_publish_without_bus(tmp_path):
    sm = SessionManager(tmp_path)
    lt, _cg = _tools(sm)
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
