from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.goal_driver import GOAL_DRIVER_META, GoalDriver
from nanobot.goals import GoalStore
from nanobot.session.automation_turns import automation_history_overrides
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager


def _setup(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = tmp_path / "goals"
    sessions = SessionManager(workspace)
    store = GoalStore.for_workspace(workspace, root=root)
    bus = MessageBus()
    return workspace, root, sessions, store, bus


def _plan(store: GoalStore, goal_id: str, version: int, *, two: bool = False):
    nodes = [
        {"id": "main", "title": "Main", "outcome": "done", "depends_on": []},
    ]
    if two:
        nodes.append(
            {"id": "other", "title": "Other", "outcome": "done", "depends_on": []}
        )
    return store.apply(goal_id, version, {"action": "plan", "nodes": nodes})


@pytest.mark.asyncio
async def test_repeated_scan_schedules_one_turn(tmp_path: Path) -> None:
    workspace, root, sessions, store, bus = _setup(tmp_path)
    goal = store.create(
        "websocket:c1",
        "finish later",
        route={"channel": "websocket", "chat_id": "c1"},
    )
    _plan(store, goal.id, goal.version)
    driver = GoalDriver(workspace, bus, sessions, store_root=root)

    await asyncio.gather(driver.scan_once(), driver.scan_once())
    await driver.scan_once()

    assert bus.inbound_size == 1
    message = await bus.consume_inbound()
    assert message.metadata[GOAL_DRIVER_META]["start_version"] == 2
    text, extra = automation_history_overrides(message.metadata)
    assert text == message.content
    assert extra["_automation_turn"]["kind"] == "goal_driver"


@pytest.mark.asyncio
async def test_restart_reschedules_unfinished_goal_immediately(tmp_path: Path) -> None:
    workspace, root, sessions, store, old_bus = _setup(tmp_path)
    goal = store.create("websocket:c1", "finish after restart")
    _plan(store, goal.id, goal.version)
    await GoalDriver(workspace, old_bus, sessions, store_root=root).scan_once()

    new_bus = MessageBus()
    await GoalDriver(workspace, new_bus, sessions, store_root=root).scan_once()

    assert new_bus.inbound_size == 1
    message = await new_bus.consume_inbound()
    assert message.metadata[GOAL_DRIVER_META]["goal_id"] == goal.id
    ref = sessions.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]
    assert ref["goal_id"] == goal.id


@pytest.mark.asyncio
async def test_interrupted_running_node_waits_and_reports(tmp_path: Path) -> None:
    workspace, root, sessions, store, bus = _setup(tmp_path)
    goal = store.create("websocket:c1", "safe work")
    goal = _plan(store, goal.id, goal.version)
    store.apply(goal.id, goal.version, {"action": "begin", "node_id": "main"})
    driver = GoalDriver(workspace, bus, sessions, store_root=root)

    await driver.scan_once()

    stored = store.get(goal.id)
    assert stored is not None and stored.status == "waiting"
    assert "duplicate side effects" in stored.state["status_reason"]
    assert bus.inbound_size == 0
    assert "paused" in (await bus.consume_outbound()).content
    assert sessions.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]["status"] == "waiting"


@pytest.mark.asyncio
async def test_exhausted_recovery_keeps_independent_ready_work(tmp_path: Path) -> None:
    workspace, root, sessions, store, bus = _setup(tmp_path)
    goal = store.create("websocket:c1", "keep independent work")
    goal = _plan(store, goal.id, goal.version, two=True)
    goal = store.apply(
        goal.id,
        goal.version,
        {"action": "block", "node_id": "main", "reason": "route unavailable"},
    )
    for _ in range(4):
        goal = store.apply(
            goal.id,
            goal.version,
            {"action": "recovery_attempt", "node_id": "main"},
        )

    await GoalDriver(workspace, bus, sessions, store_root=root).scan_once()

    stored = store.get(goal.id)
    assert stored is not None and stored.status == "active"
    assert bus.inbound_size == 1
    assert "ready_frontier" in (await bus.consume_inbound()).content


@pytest.mark.asyncio
async def test_exhausted_recovery_without_other_path_waits_and_reports(tmp_path: Path) -> None:
    workspace, root, sessions, store, bus = _setup(tmp_path)
    goal = store.create("websocket:c1", "try recoveries")
    goal = _plan(store, goal.id, goal.version)
    goal = store.apply(
        goal.id,
        goal.version,
        {"action": "block", "node_id": "main", "reason": "route unavailable"},
    )
    for _ in range(4):
        goal = store.apply(
            goal.id,
            goal.version,
            {"action": "recovery_attempt", "node_id": "main"},
        )

    await GoalDriver(workspace, bus, sessions, store_root=root).scan_once()

    stored = store.get(goal.id)
    assert stored is not None and stored.status == "waiting"
    assert "needs user input" in (await bus.consume_outbound()).content
    resumed = store.set_status(stored.id, stored.version, "active", "user supplied context")
    assert resumed.state["recovery_attempts"] == 0


@pytest.mark.asyncio
async def test_three_driver_turns_without_progress_pause_the_goal(tmp_path: Path) -> None:
    workspace, root, sessions, store, bus = _setup(tmp_path)
    goal = store.create("websocket:c1", "make progress")
    _plan(store, goal.id, goal.version)
    driver = GoalDriver(workspace, bus, sessions, store_root=root)
    await driver.scan_once()

    for _ in range(3):
        message = await bus.consume_inbound()
        await driver.after_turn(message)

    stored = store.get(goal.id)
    assert stored is not None and stored.status == "waiting"
    assert "no durable progress" in (await bus.consume_outbound()).content
