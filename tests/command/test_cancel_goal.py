import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import GoalStateSyncEvent
from nanobot.bus.queue import MessageBus
from nanobot.goal.assembly import install_goal
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import WebuiTurnCoordinator
from nanobot.webui.session_projection import WebUISessionProjection


@pytest.fixture
async def loop(tmp_path):
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="Answer."))
    agent = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path,
                      model="test-model", builtin_assembly=install_goal)
    WebuiTurnCoordinator(bus=agent.bus, sessions=agent.sessions,
                         schedule_background=lambda coro: coro.close()).subscribe()
    try:
        yield agent
    finally:
        await agent.aclose()


def cancel_message(channel="websocket"):
    return InboundMessage(channel=channel, sender_id="user", chat_id="cancel",
                          content="/cancel_goal")


@pytest.mark.parametrize("status", ["active", "blocked"])
async def test_user_command_cancels_goal_without_a_model_and_survives_reconnect(loop, tmp_path, status):
    msg = cancel_message()
    session = await loop.sessions.state.get(msg.session_key)
    await loop.sessions.state.update_metadata(session.key, {
        GOAL_STATE_KEY: {"status": status, "objective": "Finish the task"},
    })
    await loop._dispatch_inbound(msg)
    goal = (await loop.sessions.state.read_header(session.key)).metadata[GOAL_STATE_KEY]
    assert goal["status"] == "cancelled"
    assert SessionManager(tmp_path).get_or_create(session.key).metadata[GOAL_STATE_KEY] == goal
    outbound = []
    while not loop.bus.outbound.empty():
        outbound.append(loop.bus.outbound.get_nowait())
    assert outbound[-1].content == "Goal cancelled."
    sync = [item.event for item in outbound if isinstance(item.event, GoalStateSyncEvent)]
    assert [event.goal_state for event in sync] == [{"active": False}]
    assert await WebUISessionProjection(loop.sessions).persisted_goal_state(session.key) == {"active": False}
    await loop._dispatch_inbound(msg)
    assert loop.bus.outbound.get_nowait().content == "No goal to cancel."
    assert (await loop.sessions.state.read_header(session.key)).metadata[GOAL_STATE_KEY] == goal
    loop.provider.chat_stream_with_retry.assert_not_awaited()


@pytest.mark.parametrize("status", ["active", "blocked"])
async def test_cancel_stops_active_goal_work_but_not_unrelated_work_for_blocked_goal(loop, status):
    msg = cancel_message("telegram")
    session = await loop.sessions.state.get(msg.session_key)
    await loop.sessions.state.update_metadata(session.key, {
        GOAL_STATE_KEY: {"status": status, "objective": "Finish the task"},
    })
    entered, release, interrupted = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def respond(**_kwargs):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            interrupted.set()
            raise
        return LLMResponse(content="Answer.")

    loop.provider.chat_stream_with_retry.side_effect = respond
    await loop._dispatch_inbound(InboundMessage(
        channel=msg.channel, sender_id="user", chat_id=msg.chat_id, content="Continue chatting",
    ))
    await asyncio.wait_for(entered.wait(), 3)
    worker = tuple(loop._active_tasks[session.key])
    await asyncio.wait_for(loop._dispatch_inbound(msg), 3)
    assert interrupted.is_set() == (status == "active")
    assert (await loop.sessions.state.read_header(session.key)).metadata[GOAL_STATE_KEY]["status"] == "cancelled"
    release.set()
    await asyncio.gather(*worker, return_exceptions=True)
    assert loop.provider.chat_stream_with_retry.await_count == 1
    assert (await loop.sessions.state.read_header(session.key)).metadata[GOAL_STATE_KEY]["status"] == "cancelled"


@pytest.mark.parametrize("source", ["automation", "subagent", "stale"])
async def test_cancellation_requires_a_current_user_request(loop, source):
    msg = cancel_message()
    session = await loop.sessions.state.get(msg.session_key)
    if source == "automation":
        msg.metadata = {"_cron_trigger": {"job_id": "job"}}
    elif source == "subagent":
        msg.sender_id = "subagent"
    else:
        msg.session_generation = session.generation
        await loop.sessions.state.reset(session.key)
        session = await loop.sessions.state.get_header(session.key)
    await loop.sessions.state.update_metadata(session.key, {
        GOAL_STATE_KEY: {"status": "blocked", "objective": "Keep this goal"},
    })
    await loop._dispatch_inbound(msg)
    assert (await loop.sessions.state.read_header(session.key)).metadata[GOAL_STATE_KEY]["status"] == "blocked"
    reply = loop.bus.outbound.get_nowait()
    assert "only be cancelled by a user" in reply.content or "changed" in reply.content
    loop.provider.chat_stream_with_retry.assert_not_awaited()


async def test_cancel_save_failure_keeps_goal_visible_and_reports_failure(loop, monkeypatch):
    msg = cancel_message()
    await loop.sessions.state.get(msg.session_key)
    await loop.sessions.state.update_metadata(msg.session_key, {
        GOAL_STATE_KEY: {"status": "blocked", "objective": "Keep this goal"},
    })
    replace_metadata = loop.sessions._store.replace_metadata

    def fail_cancellation(key, metadata, **kwargs):
        if metadata.get(GOAL_STATE_KEY, {}).get("status") == "cancelled":
            raise sqlite3.OperationalError("disk full")
        return replace_metadata(key, metadata, **kwargs)

    monkeypatch.setattr(loop.sessions._store, "replace_metadata", fail_cancellation)
    await loop._dispatch_inbound(msg)
    reply = loop.bus.outbound.get_nowait()
    assert "Could not save" in reply.content
    assert loop.bus.outbound.empty()
    goal = await WebUISessionProjection(loop.sessions).persisted_goal_state(msg.session_key)
    assert goal["status"] == "blocked"


async def test_direct_command_preserves_cancelled_goal_when_saving_command_history(loop):
    key = "cli:direct"
    await loop.sessions.state.get(key)
    await loop.sessions.state.update_metadata(key, {
        GOAL_STATE_KEY: {"status": "active", "objective": "Cancel this task"},
    })
    result = await loop.process_direct("/cancel_goal")
    assert result.content == "Goal cancelled."
    saved = await loop.sessions.state.read(key)
    assert saved.metadata[GOAL_STATE_KEY]["status"] == "cancelled"
    loop.provider.chat_stream_with_retry.assert_not_awaited()
