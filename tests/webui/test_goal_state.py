import json

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import GoalStateSyncEvent, TurnEndEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import GoalStateChanged, RuntimeEventContext
from nanobot.session.goal_state import GOAL_STATE_KEY, goal_state_runtime_lines
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import WebuiTurnCoordinator
from nanobot.webui.goal_state import goal_state_ws_blob
from nanobot.webui.session_projection import WebUISessionProjection


def test_goal_state_ws_blob_inactive_when_missing_or_completed():
    assert goal_state_ws_blob(None) == {"active": False}
    assert goal_state_ws_blob({}) == {"active": False}
    assert goal_state_ws_blob({GOAL_STATE_KEY: {"status": "completed", "objective": "x"}}) == {
        "active": False,
    }


@pytest.mark.parametrize("current_goal", [None, {"status": "completed"}])
def test_goal_state_ws_does_not_revive_superseded_legacy_goal(current_goal):
    metadata = {
        GOAL_STATE_KEY: current_goal,
        "thread_goal": {"status": "active", "objective": "Old goal"},
    }

    assert goal_state_ws_blob(metadata) == {"active": False}


def test_goal_state_ws_blob_active_shape():
    meta = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "Build feature.",
            "ui_summary": "feat",
        },
    }
    assert goal_state_ws_blob(meta) == {
        "active": True,
        "status": "active",
        "ui_summary": "feat",
        "objective": "Build feature.",
    }


def test_goal_state_ws_blob_preserves_blocked_state_for_host_attention():
    meta = {
        GOAL_STATE_KEY: {
            "status": "blocked",
            "objective": "Deploy safely.",
            "ui_summary": "Approval required",
            "recap": "Production access is required.",
        },
    }
    assert goal_state_ws_blob(meta) == {
        "active": False,
        "status": "blocked",
        "ui_summary": "Approval required",
        "objective": "Deploy safely.",
        "recap": "Production access is required.",
    }


def test_goal_state_ws_truncation_is_display_only_for_legacy_json():
    objective = "x" * 598 + "  " + "finish the objective"
    summary = "s" * 130
    recap = "r" * 250
    legacy_goal = json.dumps({
        "status": "active",
        "objective": objective,
        "ui_summary": summary,
        "recap": recap,
    })
    metadata = {"thread_goal": legacy_goal}

    assert goal_state_ws_blob(metadata) == {
        "active": True,
        "status": "active",
        "objective": "x" * 598 + "…",
        "ui_summary": summary[:120],
        "recap": recap[:240],
    }
    assert metadata["thread_goal"] == legacy_goal
    assert goal_state_runtime_lines(metadata) == [
        "Goal (active):", objective, f"Summary: {summary}",
    ]


async def test_long_goal_uses_same_display_snapshot_for_live_end_and_reconnect(tmp_path):
    sessions = SessionManager(tmp_path)
    bus = MessageBus()
    coordinator = WebuiTurnCoordinator(
        bus=bus, sessions=sessions, schedule_background=lambda coro: coro.close(),
    )
    coordinator.subscribe()
    key = "websocket:goal-view"
    objective = "x" * 700
    metadata = {GOAL_STATE_KEY: {"status": "active", "objective": objective}}
    expected = {"active": True, "status": "active", "objective": "x" * 600 + "…"}
    try:
        await sessions.state.get(key)
        await sessions.state.update_metadata(key, metadata)
        await bus.publish(GoalStateChanged(
            context=RuntimeEventContext(channel="websocket", chat_id="goal-view", session_key=key),
            session_metadata=metadata,
        ))
        live_event = bus.outbound.get_nowait().event
        assert isinstance(live_event, GoalStateSyncEvent)
        assert live_event.goal_state == expected

        await coordinator.handle_turn_end(
            InboundMessage(channel="websocket", sender_id="user", chat_id="goal-view", content="go"),
            session_key=key, latency_ms=None,
        )
        end_event = bus.outbound.get_nowait().event
        assert isinstance(end_event, TurnEndEvent)
        assert end_event.goal_state == expected

        assert await WebUISessionProjection(sessions).hydration_events(key, "goal-view") == (
            {"event": "goal_state", "chat_id": "goal-view", "goal_state": expected},
        )
        stored = await sessions.state.read_metadata(key)
        assert stored is not None
        assert stored["metadata"][GOAL_STATE_KEY]["objective"] == objective
    finally:
        await sessions.state.aclose()
