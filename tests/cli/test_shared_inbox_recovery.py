"""Real gateway/channel/inbox recovery composition, without starting any transport."""
from datetime import datetime

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.cli.gateway_runtime import _bind_shared_inbox_recovery
from nanobot.config.schema import Config, GoalRecoveryConfig
from nanobot.session.goal_recovery import GOAL_RECOVERY_KEY, GoalRecoveryWatchdog
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import (
    PENDING_FOLLOWUPS_KEY,
    PENDING_USER_TURN_KEY,
    RECOVERY_METADATA_KEY,
    RUNTIME_CHECKPOINT_KEY,
    RecoveryActionError,
    RecoveryCoordinator,
    record_pending_followup,
)


@pytest.fixture(autouse=True)
def isolated_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")


def compose(tmp_path, *, shared=True, unified=True):
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    bus = MessageBus()
    recovery = RecoveryCoordinator(sessions, bus, unified_session=unified, auto_goal_recovery=True)
    config = Config.model_validate({
        "agents": {"defaults": {"workspace": str(tmp_path / "workspace"), "unifiedSession": unified}},
        "channels": {"telegram": {
            "enabled": True, "token": "123:fixture", "allowFrom": ["7"],
            "technical": {"enabled": True, "chatId": "-1007", "mainChatId": "7", "sharedInbox": shared},
        }},
    })
    channels = ChannelManager(
        config, bus, session_manager=sessions, config_path=tmp_path / "config.json",
        webui_recovery_action=recovery.handle_action,
    )
    _bind_shared_inbox_recovery(recovery, channels)
    return recovery, channels, sessions, bus


def saved_goal(sessions, key):
    session = sessions.get_or_create(key)
    session.add_message("user", "/goal inspect saved logs")
    session.metadata["goal_state"] = {"status": "active", "objective": "inspect saved logs", "started_at": "2026-01-01"}
    session.metadata[PENDING_USER_TURN_KEY] = True
    sessions.save(session)
    return session


def watchdog(sessions, bus):
    return GoalRecoveryWatchdog(
        sessions, bus, GoalRecoveryConfig(enabled=True), is_busy=lambda _: False,
        is_channel_enabled=lambda _: True, clock=lambda: datetime.now().timestamp() + 7200,
    )


@pytest.mark.parametrize("key,chat_id", [("websocket:ordinary", "ordinary"), ("telegram:7", "shared-main")])
@pytest.mark.parametrize("uncertain", [False, True])
async def test_composed_startup_requeues_only_safe_followup(tmp_path, key, chat_id, uncertain):
    _, original_channels, original, _ = compose(tmp_path)
    assert original_channels._shared_inbox.active
    session = saved_goal(original, key)
    followup_id = record_pending_followup(session, InboundMessage(
        channel="websocket", chat_id=chat_id, sender_id="owner", content="also check saved logs",
        metadata={"webui": True}, session_key_override=key,
    ))
    if uncertain:
        call = {"id": "send-1", "function": {"name": "send_email", "arguments": "{}"}}
        session.metadata[RUNTIME_CHECKPOINT_KEY] = {
            "phase": "awaiting_tools", "assistant_message": {"role": "assistant", "content": "", "tool_calls": [call]},
            "completed_tool_results": [], "pending_tool_calls": [call],
        }
    original.save(session)

    recovery, channels, restarted, bus = compose(tmp_path)
    assert channels._shared_inbox.session_key("websocket", chat_id) == key
    await recovery.scan()
    service = watchdog(restarted, bus)
    await service.tick()
    restored = restarted.get_or_create(key)
    assert restored.metadata[PENDING_FOLLOWUPS_KEY][0]["id"] == followup_id
    if uncertain:
        assert bus.inbound.empty()
        assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "tool_state_unknown"
        assert restored.messages[-1]["_recovery_interrupted"] is True
        assert RUNTIME_CHECKPOINT_KEY not in restored.metadata
        # A second process still neither replays the tool nor treats the journal as approval.
        recovery, _, restarted, bus = compose(tmp_path)
        await recovery.scan()
        await watchdog(restarted, bus).tick()
        assert bus.inbound.empty()
        assert restarted.get_or_create(key).metadata[RECOVERY_METADATA_KEY]["reason"] == "tool_state_unknown"
    else:
        assert bus.inbound.qsize() == 1
        queued = bus.inbound.get_nowait()
        assert queued.session_key == key and queued.chat_id == chat_id
        assert queued.require_existing_session
        assert queued.metadata["_recovery_followup_id"] == followup_id
        assert restored.metadata[GOAL_RECOVERY_KEY]["reason"] == "pending_user_followups"
        assert await recovery.admit(queued)
    assert restarted.read_session_metadata("websocket:shared-main") is None
    assert restarted.read_session_metadata("unified:default") is None


@pytest.mark.parametrize("action", ["continue", "dismiss"])
@pytest.mark.parametrize("key,chat_id", [("telegram:7", "shared-main"), ("websocket:ordinary", "ordinary")])
async def test_composed_actions_use_canonical_key_not_legacy_unified(tmp_path, action, key, chat_id):
    recovery, _, sessions, bus = compose(tmp_path)
    session = saved_goal(sessions, key)
    session.metadata[RECOVERY_METADATA_KEY] = {"status": "awaiting_user", "recovery_id": "current"}
    sessions.save(session)
    others = {}
    for other_key in ("unified:default", "telegram:8", "websocket:other"):
        other = saved_goal(sessions, other_key)
        # Deliberately colliding recovery IDs must not redirect an action.
        other.metadata[RECOVERY_METADATA_KEY] = {"status": "awaiting_user", "recovery_id": "current"}
        other.metadata["last_channel"] = "websocket:shared-main"
        sessions.save(other)
        others[other_key] = sessions.read_session_file(other_key)
    with pytest.raises(RecoveryActionError, match="stale"):
        await recovery.handle_action(action, {"chat_id": chat_id, "recovery_id": "stale"})
    assert bus.inbound.empty()
    state = await recovery.handle_action(action, {"chat_id": chat_id, "recovery_id": "current"})
    assert session.metadata[RECOVERY_METADATA_KEY]["reason"] == ("user_confirmed" if action == "continue" else "dismissed")
    if action == "continue":
        assert state["status"] == "resuming"
        queued = bus.inbound.get_nowait()
        assert queued.session_key == key and queued.chat_id == chat_id
        assert await recovery.admit(queued)
        await recovery.turn_completed(key)
        assert session.metadata[RECOVERY_METADATA_KEY]["reason"] == "continued"
    assert bus.inbound.empty()
    while not bus.outbound.empty():
        assert bus.outbound.get_nowait().chat_id == chat_id
    for other_key, before in others.items():
        assert sessions.read_session_file(other_key) == before
    assert sessions.read_session_metadata("websocket:shared-main") is None


async def test_composed_resolver_revokes_actions_and_queued_work_when_inbox_inactive(tmp_path):
    recovery, channels, sessions, bus = compose(tmp_path)
    session = saved_goal(sessions, "telegram:7")
    session.metadata[RECOVERY_METADATA_KEY] = {"status": "awaiting_user", "recovery_id": "review"}
    sessions.save(session)
    await recovery.handle_action("continue", {"chat_id": "shared-main", "recovery_id": "review"})
    queued = bus.inbound.get_nowait()
    channels._shared_inbox.active = False
    assert not await recovery.admit(queued)
    for chat_id in ("shared-main", "shared-notifications"):
        with pytest.raises(RecoveryActionError, match="unavailable"):
            await recovery.handle_action("dismiss", {"chat_id": chat_id, "recovery_id": "review"})
        assert sessions.read_session_metadata(f"websocket:{chat_id}") is None
    assert recovery._session_key("ordinary") == "websocket:ordinary"
    before = sessions.read_session_file(session.key)
    await recovery.scan()
    assert bus.inbound.empty()
    assert sessions.read_session_file(session.key) == before


@pytest.mark.parametrize("shared", [False, True])
async def test_scan_never_infers_owner_from_telegram_or_last_channel(tmp_path, shared):
    recovery, channels, sessions, bus = compose(tmp_path, shared=shared)
    if shared:
        channels._shared_inbox.active = False
    before = {}
    for key in ("telegram:7", "telegram:8", "websocket:shared-main", "websocket:shared-notifications"):
        session = saved_goal(sessions, key)
        session.metadata["last_channel"] = "websocket:shared-main"
        record_pending_followup(session, InboundMessage(channel="websocket", chat_id="shared-main", sender_id="user", content="saved"))
        sessions.save(session)
        before[key] = sessions.read_session_file(key)
    await recovery.scan()
    assert bus.inbound.empty() and bus.outbound.empty()
    for key, data in before.items():
        assert sessions.read_session_file(key) == data


async def test_composed_scan_leaves_legacy_unified_untouched(tmp_path):
    recovery, _, sessions, bus = compose(tmp_path)
    session = saved_goal(sessions, "unified:default")
    session.metadata["last_channel"] = "websocket:ordinary"
    record_pending_followup(session, InboundMessage(channel="websocket", chat_id="ordinary", sender_id="user", content="legacy"))
    sessions.save(session)
    before = sessions.read_session_file(session.key)
    await recovery.scan()
    assert bus.inbound.empty() and bus.outbound.empty()
    assert sessions.read_session_file(session.key) == before


@pytest.mark.parametrize("malformed", [False, True])
async def test_shared_tool_review_actions_do_not_replay_or_clear_approval(tmp_path, malformed):
    recovery, _, sessions, bus = compose(tmp_path)
    session = saved_goal(sessions, "telegram:7")
    session.metadata["pending_approval"] = True
    call = {"id": "send-1", "function": {"name": "send_email", "arguments": "{}"}}
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {"phase": "future"} if malformed else {
        "phase": "awaiting_tools", "assistant_message": {"role": "assistant", "content": "", "tool_calls": [call]},
        "completed_tool_results": [], "pending_tool_calls": [call],
    }
    sessions.save(session)
    await recovery.scan()
    assert bus.inbound.empty()
    state = session.metadata[RECOVERY_METADATA_KEY]
    assert state["status"] == "awaiting_user"
    payload = {"chat_id": "shared-main", "recovery_id": state["recovery_id"]}
    if malformed:
        with pytest.raises(RecoveryActionError, match="context is unavailable"):
            await recovery.handle_action("continue", payload)
        await recovery.handle_action("dismiss", payload)
    else:
        # Continue is explicit human review of uncertainty, not a tool replay.
        assert session.messages[-1]["_recovery_interrupted"] is True
        before = list(session.messages)
        await recovery.handle_action("continue", payload)
        queued = bus.inbound.get_nowait()
        assert queued.session_key == "telegram:7" and queued.chat_id == "shared-main"
        assert queued.metadata["_webui_recovery_id"] == state["recovery_id"]
        assert session.messages == before
    assert session.metadata["pending_approval"] is True
    assert bus.inbound.empty()
    assert sessions.read_session_metadata("websocket:shared-main") is None
