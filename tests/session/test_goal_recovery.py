"""Restart simulations use new managers/buses, no real sleeps, providers, or gateway."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import GatewayConfig, GoalRecoveryConfig
from nanobot.session.goal_recovery import (
    GOAL_RECOVERY_INBOUND_KEY,
    GOAL_RECOVERY_KEY,
    GoalRecoveryWatchdog,
)
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import (
    PENDING_USER_TURN_KEY,
    RECOVERY_METADATA_KEY,
    RUNTIME_CHECKPOINT_KEY,
    RecoveryCoordinator,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    # The legacy WebUI transcript index is instance-scoped, not workspace-scoped.
    monkeypatch.setenv("HOME", str(tmp_path))


def setup(tmp_path, *, enabled=True, now=None, busy=None, channel=True):
    sessions, bus = SessionManager(tmp_path / "workspace"), MessageBus()
    now = now if now is not None else [datetime.now().timestamp() + 1200]
    busy = busy if busy is not None else set()
    service = GoalRecoveryWatchdog(
        sessions, bus, GoalRecoveryConfig(enabled=enabled),
        is_busy=lambda key: key in busy,
        is_channel_enabled=lambda _: channel,
        clock=lambda: now[0],
    )
    return service, sessions, bus, now


def goal(sessions, key="websocket:chat"):
    session = sessions.get_or_create(key)
    session.messages = [{"role": "user", "content": "/goal verify the project"}]
    session.metadata["goal_state"] = {
        "status": "active", "objective": "verify the project", "started_at": "2026-01-01",
    }
    session.updated_at = datetime(2026, 1, 1)
    sessions.save(session)
    return session


def checkpoint(phase="tools_completed"):
    call = {"id": "read-1", "function": {"name": "read_file", "arguments": "{}"}}
    return {
        "phase": phase,
        "assistant_message": {"role": "assistant", "content": "", "tool_calls": [call]},
        "pending_tool_calls": [call] if phase == "awaiting_tools" else [],
        "completed_tool_results": [] if phase == "awaiting_tools" else [
            {"role": "tool", "tool_call_id": "read-1", "content": "saved result"},
        ],
    }


def test_config_explicit_opt_in_and_aliases():
    assert GatewayConfig().goal_recovery.enabled is False
    assert GatewayConfig().goal_recovery.interval_seconds == 600
    cfg = GatewayConfig.model_validate({"goalRecovery": {"enabled": True, "intervalSeconds": 600}})
    assert cfg.goal_recovery.enabled
    with pytest.raises(ValidationError):
        GoalRecoveryConfig(interval_seconds=0)


async def test_disabled_never_queues(tmp_path):
    service, sessions, bus, _ = setup(tmp_path, enabled=False)
    goal(sessions)
    await service.tick()
    await service.run()
    assert bus.inbound.empty()


async def test_restart_safe_checkpoint_then_watchdog_advances_once(tmp_path):
    _, sessions, _, now = setup(tmp_path)
    session = goal(sessions)
    session.metadata.update({PENDING_USER_TURN_KEY: True, RUNTIME_CHECKPOINT_KEY: checkpoint()})
    sessions.save(session)

    service, restarted, bus, _ = setup(tmp_path, now=now)
    recovery = RecoveryCoordinator(restarted, bus, auto_goal_recovery=True)
    await recovery.scan()
    assert bus.inbound.empty()  # Startup only classifies; timer owns model work.
    restored = restarted.get_or_create(session.key)
    assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "goal_watchdog_scheduled"
    assert restored.messages[-1]["content"] == "saved result"
    await service.tick()
    queued = bus.inbound.get_nowait()
    assert queued.require_existing_session
    assert queued.input_role == "system"
    assert queued.metadata["_skip_user_persist"] is True
    assert service.claim(queued)
    assert not service.claim(queued)  # duplicate bus delivery
    assert sum(row.get("content") == "saved result" for row in restored.messages) == 1
    await service.tick()
    assert bus.inbound.empty()
    service.finish(queued, "completed")
    durable = SessionManager(tmp_path / "workspace").get_or_create(session.key)
    assert durable.metadata[GOAL_RECOVERY_KEY]["status"] == "waiting"
    assert [row["status"] for row in durable.metadata[GOAL_RECOVERY_KEY]["history"]] == [
        "queued", "running", "waiting",
    ]
    await service.tick()
    assert bus.inbound.empty()
    now[0] += 601
    await service.tick()
    assert bus.inbound.qsize() == 1


@pytest.mark.parametrize("status", ["completed", "cancelled", "canceled", "blocked", "paused", "closed", "pending_confirmation"])
async def test_nonactive_goals_never_resume(tmp_path, status):
    service, sessions, bus, _ = setup(tmp_path)
    session = goal(sessions)
    session.metadata["goal_state"]["status"] = status
    sessions.save(session)
    await service.tick()
    assert bus.inbound.empty()
    assert session.metadata["goal_state"]["status"] == status


@pytest.mark.parametrize("hold", ["paused", "closed", "pending_confirmation", "pending_approval"])
async def test_session_holds_are_preserved(tmp_path, hold):
    service, sessions, bus, _ = setup(tmp_path)
    session = goal(sessions)
    session.metadata[hold] = True
    sessions.save(session)
    await service.tick()
    assert bus.inbound.empty()
    assert session.metadata[hold] is True


@pytest.mark.parametrize("state", ["awaiting_user", "failed", "resuming"])
async def test_preexisting_confirmation_is_never_overridden_by_opt_in(tmp_path, state):
    service, sessions, bus, _ = setup(tmp_path)
    session = goal(sessions)
    session.metadata[RECOVERY_METADATA_KEY] = {"status": state, "recovery_id": "old"}
    sessions.save(session)
    await RecoveryCoordinator(sessions, bus, auto_goal_recovery=True).scan()
    await service.tick()
    assert bus.inbound.empty()


async def test_uncertain_tools_hold_across_repeated_restarts(tmp_path):
    _, sessions, _, now = setup(tmp_path)
    session = goal(sessions)
    session.metadata[RUNTIME_CHECKPOINT_KEY] = checkpoint("awaiting_tools")
    sessions.save(session)
    for _ in range(3):
        service, restarted, bus, _ = setup(tmp_path, now=now)
        await RecoveryCoordinator(restarted, bus, auto_goal_recovery=True).scan()
        await service.tick()
        assert bus.inbound.empty()
        restored = restarted.get_or_create(session.key)
        assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "tool_state_unknown"
        now[0] += 7200


async def test_busy_then_duplicate_ticks_and_admission_race(tmp_path):
    busy = {"websocket:chat"}
    service, sessions, bus, _ = setup(tmp_path, busy=busy)
    goal(sessions)
    await service.tick()
    assert bus.inbound.empty()
    busy.clear()
    await asyncio.gather(service.tick(), service.tick())
    assert bus.inbound.qsize() == 1
    queued = bus.inbound.get_nowait()
    busy.add(queued.session_key)
    assert not service.observe_inbound(queued, queued.session_key)
    assert not service.claim(queued)


async def test_stop_and_cancel_are_durable_and_new_input_supersedes(tmp_path):
    service, sessions, bus, now = setup(tmp_path)
    session = goal(sessions)
    await service.tick()
    queued = bus.inbound.get_nowait()
    stop = InboundMessage(channel="websocket", chat_id="chat", sender_id="user", content="/stop")
    assert service.observe_inbound(stop, session.key)
    service.finish(queued, "cancelled")  # must not overwrite the user's newer pause
    assert not service.claim(queued)
    service, restarted, bus, _ = setup(tmp_path, now=now)
    now[0] += 7200
    await service.tick()
    assert bus.inbound.empty()
    assert restarted.get_or_create(session.key).metadata[GOAL_RECOVERY_KEY]["status"] == "paused"
    stop.content = "/help"
    service.observe_inbound(stop, session.key)
    assert restarted.get_or_create(session.key).metadata[GOAL_RECOVERY_KEY]["status"] == "paused"
    stop.content = "/goal continue verifying the project safely"
    service.observe_inbound(stop, session.key)
    await service.tick()
    assert bus.inbound.empty()
    now[0] += 601
    await service.tick()
    assert bus.inbound.qsize() == 1


async def test_delete_or_goal_cancel_after_queue_cannot_resurrect(tmp_path):
    service, sessions, bus, _ = setup(tmp_path)
    session = goal(sessions)
    await service.tick()
    queued = bus.inbound.get_nowait()
    session.metadata["goal_state"]["status"] = "cancelled"
    sessions.save(session)
    assert not service.claim(queued)
    sessions.delete_session(session.key)
    assert not service.claim(queued)
    await service.tick()
    assert sessions.read_session_metadata(session.key) is None


async def test_failure_backoff_survives_restart_and_is_bounded(tmp_path):
    service, sessions, bus, now = setup(tmp_path)
    session = goal(sessions)
    for expected_delay in (1200, 2400, 3600, 3600):
        await service.tick()
        queued = bus.inbound.get_nowait()
        assert service.claim(queued)
        service.finish(queued, "error")
        record = sessions.get_or_create(session.key).metadata[GOAL_RECOVERY_KEY]
        assert record["next_attempt_at"] == now[0] + expected_delay
        service, sessions, bus, _ = setup(tmp_path, now=now)
        now[0] += expected_delay - 1
        await service.tick()
        assert bus.inbound.empty()
        now[0] += 1


async def test_crash_after_claim_replaces_id_without_replaying_tools(tmp_path):
    service, sessions, bus, now = setup(tmp_path)
    session = goal(sessions, "telegram:123")
    await service.tick()
    lost = bus.inbound.get_nowait()
    assert service.claim(lost)
    service, restarted, bus, _ = setup(tmp_path, now=now)
    await service.tick()
    assert bus.inbound.empty()
    now[0] += 601
    await service.tick()
    replacement = bus.inbound.get_nowait()
    assert replacement.metadata[GOAL_RECOVERY_INBOUND_KEY] != lost.metadata[GOAL_RECOVERY_INBOUND_KEY]
    assert not service.claim(lost)
    assert service.claim(replacement)
    assert restarted.get_or_create(session.key).metadata[GOAL_RECOVERY_KEY]["failures"] == 1


async def test_no_channel_and_corrupt_checkpoint_fail_closed(tmp_path):
    service, sessions, bus, _ = setup(tmp_path, channel=False)
    session = goal(sessions)
    await service.tick()
    assert bus.inbound.empty()
    assert session.metadata[GOAL_RECOVERY_KEY]["reason"] == "channel_unavailable"
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {"phase": "future"}
    sessions.save(session)
    await service.tick()
    assert bus.inbound.empty()
    assert session.metadata[GOAL_RECOVERY_KEY]["reason"] == "checkpoint_invalid"


async def test_enqueue_failure_is_durable_and_retries_after_cooldown(tmp_path, monkeypatch):
    service, sessions, bus, now = setup(tmp_path)
    session = goal(sessions)
    monkeypatch.setattr(bus, "publish_inbound", AsyncMock(side_effect=RuntimeError("queue failed")))
    await service.tick()
    record = sessions.get_or_create(session.key).metadata[GOAL_RECOVERY_KEY]
    assert record["status"] == "failed"
    assert record["next_attempt_at"] == now[0] + 1200


async def test_native_timer_waits_full_interval_and_cancels_cleanly(tmp_path, monkeypatch):
    service, _, _, _ = setup(tmp_path)
    entered = asyncio.Event()
    delays = []

    async def sleep(delay):
        delays.append(delay)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("nanobot.session.goal_recovery.asyncio.sleep", sleep)
    service.tick = AsyncMock()
    task = asyncio.create_task(service.run())
    await entered.wait()
    assert delays == [600]
    service.tick.assert_not_awaited()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_confirmation_appearing_after_queue_is_not_superseded(tmp_path):
    service, sessions, bus, _ = setup(tmp_path)
    session = goal(sessions)
    await service.tick()
    queued = bus.inbound.get_nowait()
    session.metadata[RECOVERY_METADATA_KEY] = {
        "status": "awaiting_user", "recovery_id": "needs-approval", "reason": "tool_state_unknown",
    }
    sessions.save(session)
    # This admission runs before the under-lock watchdog claim in AgentLoop.
    assert not await RecoveryCoordinator(sessions, bus).admit(queued)
    assert session.metadata[RECOVERY_METADATA_KEY]["status"] == "awaiting_user"
    assert not service.claim(queued)


async def test_shutdown_is_retryable_but_explicit_cancellation_stays_paused(tmp_path):
    service, sessions, bus, now = setup(tmp_path)
    session = goal(sessions)
    await service.tick()
    queued = bus.inbound.get_nowait()
    assert service.claim(queued)
    service.finish(queued, "cancelled", shutdown=True)
    assert session.metadata[GOAL_RECOVERY_KEY]["reason"] == "gateway_shutdown"
    service, sessions, bus, _ = setup(tmp_path, now=now)
    now[0] += 1201
    await service.tick()
    queued = bus.inbound.get_nowait()
    assert service.claim(queued)
    service.finish(queued, "cancelled")
    assert sessions.get_or_create(session.key).metadata[GOAL_RECOVERY_KEY]["status"] == "paused"
    now[0] += 10000
    await service.tick()
    assert bus.inbound.empty()


async def test_unified_route_is_durable_and_route_change_invalidates_claim(tmp_path):
    service, sessions, bus, _ = setup(tmp_path)
    session = goal(sessions, "unified:default")
    session.metadata["last_channel"] = "telegram:123"
    sessions.save(session)
    await service.tick()
    queued = bus.inbound.get_nowait()
    assert queued.channel == "telegram"
    assert queued.chat_id == "123"
    assert queued.session_key == "unified:default"
    session.metadata["last_channel"] = "websocket:other"
    sessions.save(session)
    assert not service.claim(queued)
    assert session.metadata[GOAL_RECOVERY_KEY]["reason"] == "route_changed"


async def test_durability_failure_never_enqueues_or_prevents_stop(tmp_path, monkeypatch):
    service, sessions, bus, _ = setup(tmp_path)
    session = goal(sessions)

    def fail_save(_session):
        raise OSError("disk unavailable")

    monkeypatch.setattr(sessions, "save", fail_save)
    await service.tick()
    assert bus.inbound.empty()
    stop = InboundMessage(channel="websocket", chat_id="chat", sender_id="user", content="/stop")
    assert service.observe_inbound(stop, session.key)
    assert session.metadata[GOAL_RECOVERY_KEY]["status"] == "paused"
    service.finish(stop, "cancelled")


@pytest.mark.parametrize("scope,field,value", [
    ("session", "status", "blocked"),
    ("session", "status", "closed"),
    ("session", "status", "paused"),
    ("session", "status", "completed"),
    ("session", "status", "cancelled"),
    ("session", "status", "canceled"),
    ("session", "status", "pending_confirmation"),
    ("session", "status", "awaiting_user"),
    ("session", "status", "awaiting_approval"),
    ("session", "status", {"invalid": True}),
    ("session", "paused", True),
    ("session", "closed", True),
    ("session", "pending_approval", True),
    ("session", "pending_confirmation", True),
    ("goal", "status", "blocked"),
    ("goal", "status", "completed"),
    ("goal", "status", "cancelled"),
    ("goal", "status", "paused"),
    ("goal", "paused", True),
    ("goal", "closed", True),
    ("goal", "pending_approval", True),
    ("goal", "pending_confirmation", True),
    ("session", RECOVERY_METADATA_KEY, {"status": "awaiting_user", "recovery_id": "gate"}),
    ("session", RUNTIME_CHECKPOINT_KEY, checkpoint("awaiting_tools")),
])
async def test_stop_survives_independent_hold_removal_and_restart(tmp_path, scope, field, value):
    service, sessions, bus, now = setup(tmp_path)
    session = goal(sessions, "telegram:7")
    service.observe_inbound(InboundMessage(
        channel="telegram", chat_id="7", sender_id="7", content="/stop",
    ), session.key)
    paused_id = session.metadata[GOAL_RECOVERY_KEY]["goal_id"]
    target = session.metadata if scope == "session" else session.metadata["goal_state"]
    old = target.get(field)
    target[field] = value
    sessions.save(session)
    await service.tick()
    assert session.metadata[GOAL_RECOVERY_KEY]["status"] == "paused"
    assert bus.inbound.empty()
    if old is None:
        target.pop(field)
    else:
        target[field] = old
    sessions.save(session)

    restarted, persisted, bus, _ = setup(tmp_path, now=now)
    now[0] += 7200
    await restarted.tick()
    restored = persisted.get_or_create(session.key)
    assert restored.metadata[GOAL_RECOVERY_KEY]["status"] == "paused"
    assert restored.metadata[GOAL_RECOVERY_KEY]["goal_id"] == paused_id
    assert bus.inbound.empty()


async def test_replaced_goal_does_not_inherit_stop_but_goal_command_keeps_approval(tmp_path):
    service, sessions, bus, now = setup(tmp_path)
    session = goal(sessions)
    request = InboundMessage(channel="websocket", chat_id="chat", sender_id="user", content="/stop")
    service.observe_inbound(request, session.key)
    paused_id = session.metadata[GOAL_RECOVERY_KEY]["goal_id"]
    session.metadata["goal_state"].update(objective="a replacement task", replaced_at="2026-09-12")
    sessions.save(session)
    await service.tick()
    queued = bus.inbound.get_nowait()
    assert session.metadata[GOAL_RECOVERY_KEY]["goal_id"] != paused_id
    service.observe_inbound(request, session.key)
    assert not service.claim(queued)
    session.metadata["pending_approval"] = True
    request.content = "/goal a replacement task"
    service.observe_inbound(request, session.key)
    now[0] += 7200
    await service.tick()
    assert bus.inbound.empty()
    assert session.metadata["pending_approval"] is True
    assert session.metadata[GOAL_RECOVERY_KEY]["reason"] == "pending_approval"
