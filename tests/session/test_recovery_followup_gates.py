"""Journal replay is not fresh consent, for ordinary WebUI and shared-main alike."""
from copy import deepcopy

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import GoalRecoveryConfig
from nanobot.session.goal_recovery import GOAL_RECOVERY_KEY, GoalRecoveryWatchdog
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import (
    PENDING_FOLLOWUPS_KEY,
    PENDING_USER_TURN_KEY,
    RECOVERY_METADATA_KEY,
    RecoveryCoordinator,
    pending_followups,
    record_pending_followup,
)


@pytest.fixture(autouse=True)
def isolated_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")


def make(tmp_path, key):
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    bus = MessageBus()
    recovery = RecoveryCoordinator(sessions, bus, auto_goal_recovery=True, shared_main_session_key=lambda: "telegram:7")
    session = sessions.get_or_create(key)
    session.add_message("user", "inspect the logs")
    session.metadata[PENDING_USER_TURN_KEY] = True
    record_pending_followup(session, InboundMessage(
        channel="websocket", chat_id="shared-main" if key == "telegram:7" else "ordinary",
        sender_id="user", content="also inspect older logs", session_key_override=key,
    ))
    sessions.save(session)
    return recovery, sessions, bus, session


@pytest.mark.parametrize("key", ["telegram:7", "websocket:ordinary"])
@pytest.mark.parametrize("gate", [
    "pending_approval", "pending_confirmation", "closed", "status",
    "goal_approval", "goal_confirmation", "stop",
    "awaiting_user", "failed", "resuming", "dismissed",
])
async def test_restart_journal_never_clears_independent_review(tmp_path, key, gate):
    _, sessions, _, session = make(tmp_path, key)
    if gate in {"pending_approval", "pending_confirmation", "closed"}:
        session.metadata[gate] = True
    elif gate == "status":
        session.metadata["status"] = "paused"
    elif gate in {"goal_approval", "goal_confirmation", "stop"}:
        session.metadata["goal_state"] = {"status": "active", "objective": "inspect", "started_at": "2026-01-01"}
        if gate == "stop":
            service = GoalRecoveryWatchdog(sessions, MessageBus(), GoalRecoveryConfig(enabled=True),
                                           is_busy=lambda _: False, is_channel_enabled=lambda _: True)
            service.observe_inbound(InboundMessage(channel="telegram", chat_id="7", sender_id="user", content="/stop"), key)
        else:
            session.metadata["goal_state"]["pending_approval" if gate == "goal_approval" else "pending_confirmation"] = True
    else:
        session.metadata[RECOVERY_METADATA_KEY] = {
            "status": "recovered" if gate == "dismissed" else gate,
            "recovery_id": "existing", "reason": gate,
        }
    sessions.save(session)
    journal = deepcopy(session.metadata[PENDING_FOLLOWUPS_KEY])
    recovery, restarted, bus, restored = make_restart(tmp_path, key)
    await recovery.scan()
    assert bus.inbound.empty()
    assert restored.metadata[PENDING_FOLLOWUPS_KEY] == journal
    # Even a late duplicate saved before the gate appeared cannot supersede it.
    before = deepcopy(restored.metadata)
    assert not await recovery.admit(pending_followups(restored)[0])
    assert restored.metadata == before
    if gate == "stop":
        assert restored.metadata[GOAL_RECOVERY_KEY]["status"] == "paused"
    elif gate in {"pending_approval", "pending_confirmation", "closed"}:
        assert restored.metadata[gate] is True
    elif gate in {"awaiting_user", "failed", "dismissed"}:
        assert restored.metadata[RECOVERY_METADATA_KEY]["recovery_id"] == "existing"
        assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == gate


def make_restart(tmp_path, key):
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    bus = MessageBus()
    recovery = RecoveryCoordinator(sessions, bus, auto_goal_recovery=True, shared_main_session_key=lambda: "telegram:7")
    return recovery, sessions, bus, sessions.get_or_create(key)


@pytest.mark.parametrize("gate", ["pending_approval", "awaiting_user", "stop"])
async def test_gate_appearing_after_followup_enqueue_blocks_admission(tmp_path, gate):
    recovery, sessions, bus, session = make(tmp_path, "telegram:7")
    session.metadata["goal_state"] = {"status": "active", "objective": "inspect", "started_at": "2026-01-01"}
    sessions.save(session)
    await recovery.scan()
    queued = bus.inbound.get_nowait()
    if gate == "pending_approval":
        session.metadata[gate] = True
    elif gate == "awaiting_user":
        session.metadata[RECOVERY_METADATA_KEY] = {"status": gate, "recovery_id": "new-gate"}
    else:
        service = GoalRecoveryWatchdog(sessions, bus, GoalRecoveryConfig(enabled=True),
                                       is_busy=lambda _: False, is_channel_enabled=lambda _: True)
        service.observe_inbound(InboundMessage(channel="telegram", chat_id="7", sender_id="user", content="/stop"), session.key)
    sessions.save(session)
    before = deepcopy(session.metadata)
    # AgentLoop calls watchdog observation before recovery admission. Even an old
    # journal entry containing /goal must not count as post-stop permission.
    queued.content = "/goal older saved request"
    observer = GoalRecoveryWatchdog(sessions, bus, GoalRecoveryConfig(enabled=True),
                                    is_busy=lambda _: False, is_channel_enabled=lambda _: True)
    assert observer.observe_inbound(queued, session.key)
    assert not await recovery.admit(queued)
    assert session.metadata == before
    assert len(session.metadata[PENDING_FOLLOWUPS_KEY]) == 1


async def test_followup_delivery_uses_resolver_not_saved_chat_hint(tmp_path):
    recovery, sessions, bus, session = make(tmp_path, "telegram:7")
    session.metadata[PENDING_FOLLOWUPS_KEY][0]["chat_id"] = "another-pane"
    sessions.save(session)
    await recovery.scan()
    queued = bus.inbound.get_nowait()
    assert queued.chat_id == "shared-main" and queued.session_key == session.key
    assert await recovery.admit(queued)
