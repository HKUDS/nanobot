"""Authoritative snapshots are execution observations, not transcript projections."""

from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventContext, TurnExecutionChanged
from nanobot.webui.client_contract import CORE_CAPABILITY, RUN_STATE_CAPABILITY, webui_contract
from nanobot.webui.run_state import RunStateAuthority


async def fact(bus, owner, phase, *, key="websocket:chat", channel="websocket", **kwargs):
    await bus.publish(TurnExecutionChanged(
        context=RuntimeEventContext(
            channel=channel, chat_id="chat", session_key=key,
            metadata={"webui_turn_id": f"turn-{owner}"},
        ),
        execution_id=owner, phase=phase, **kwargs,
    ))


async def test_idle_snapshot_is_explicit_and_restart_identity_is_not_shared():
    bus = MessageBus()
    old = RunStateAuthority(bus, "old-gateway")
    await fact(bus, "old-owner", "queued")
    new = RunStateAuthority(MessageBus(), "new-gateway")
    assert new.snapshot("websocket:chat") == {
        "instance_id": "new-gateway", "revision": 0, "runs": [], "completed": [],
    }
    assert len(old.snapshot("websocket:chat")["runs"]) == 1
    contract = webui_contract()
    assert contract["min_protocol"] == contract["max_protocol"] == 1
    assert CORE_CAPABILITY in contract["capabilities"]
    assert RUN_STATE_CAPABILITY in contract["capabilities"]


async def test_phases_and_clock_are_independent_and_snapshots_are_detached():
    bus = MessageBus()
    authority = RunStateAuthority(bus, "gateway")
    observed = []
    authority.subscribe(lambda key, snapshot: observed.append((key, snapshot)))
    await fact(bus, "A", "queued")
    queued = authority.snapshot("websocket:chat")
    assert queued["runs"] == [{
        "run_id": "A", "turn_id": "turn-A", "phase": "queued", "started_at": None,
    }]
    await fact(bus, "A", "running")
    running = authority.snapshot("websocket:chat")
    assert running["runs"][0]["phase"] == "running"
    assert running["runs"][0]["started_at"] is None
    assert running["revision"] > queued["revision"]
    await fact(bus, "A", "stopping")
    await fact(bus, "A", "running", started_at=42)
    assert authority.snapshot("websocket:chat")["runs"][0]["phase"] == "stopping"
    await fact(bus, "A", "exited", outcome="cancelled")
    idle = authority.snapshot("websocket:chat")
    assert idle["runs"] == []
    assert idle["completed"] == [{"run_id": "A", "turn_id": "turn-A", "outcome": "cancelled"}]
    idle["completed"][0]["outcome"] = "failed"
    assert authority.snapshot("websocket:chat")["completed"][0]["outcome"] == "cancelled"
    assert queued["runs"][0]["phase"] == "queued"
    assert [snapshot["revision"] for _, snapshot in observed] == [1, 2, 3, 4]


async def test_ending_one_owner_never_clears_another_or_reopens_from_late_status():
    bus = MessageBus()
    authority = RunStateAuthority(bus, "gateway")
    await fact(bus, "A", "queued")
    await fact(bus, "B", "queued")
    await fact(bus, "B", "running", started_at=2)
    await fact(bus, "A", "exited", outcome="completed")
    snapshot = authority.snapshot("websocket:chat")
    assert [run["run_id"] for run in snapshot["runs"]] == ["B"]
    await fact(bus, "A", "running", started_at=1)
    await fact(bus, "unknown", "running", started_at=3)
    await fact(bus, "A", "queued")
    await fact(bus, "A", "exited", outcome="failed")
    assert authority.snapshot("websocket:chat") == snapshot


async def test_system_facts_are_keyed_by_target_not_source_channel_or_chat():
    bus = MessageBus()
    authority = RunStateAuthority(bus, "gateway")
    await fact(bus, "system-A", "queued", key="websocket:target", channel="system")
    await fact(bus, "system-A", "running", key="websocket:target", channel="system")
    assert authority.snapshot("websocket:chat")["runs"] == []
    assert authority.snapshot("websocket:target")["runs"][0]["run_id"] == "system-A"
    snapshot = authority.snapshot("websocket:target")
    assert authority.execution_session_key("websocket:target", "system-A") == "websocket:target"
    assert authority.execution_session_key("websocket:chat", "system-A") is None
    assert authority.snapshot("websocket:target") == snapshot
    await fact(bus, "system-A", "exited", key="websocket:target", channel="system")
    assert authority.execution_session_key("websocket:target", "system-A") is None
    assert authority.snapshot("websocket:target")["completed"][0]["outcome"] == "unknown"
    await fact(bus, "internal", "queued", key="cron:job", channel="system")
    assert authority.snapshot("cron:job")["runs"] == []
    # A notification delivery destination is not the internal job's execution target.
    await fact(bus, "internal-delivery", "queued", key="heartbeat:default", channel="websocket")
    assert authority.snapshot("websocket:chat")["runs"] == []


async def test_completion_receipts_and_retained_idle_sessions_are_bounded():
    bus = MessageBus()
    authority = RunStateAuthority(bus, "gateway")
    for index in range(authority.RECEIPTS_PER_SESSION + 5):
        await fact(bus, str(index), "queued")
        await fact(bus, str(index), "exited", outcome="completed")
    snapshot = authority.snapshot("websocket:chat")
    assert len(snapshot["completed"]) == authority.RECEIPTS_PER_SESSION
    assert snapshot["completed"][0]["run_id"] == "5"
    for index in range(authority.RECEIPT_SESSIONS):
        key = f"websocket:chat-{index}"
        await fact(bus, str(index), "queued", key=key, channel="system")
        await fact(bus, str(index), "exited", key=key, channel="system")
    assert authority.snapshot("websocket:chat")["completed"] == []
    assert authority.snapshot("websocket:chat")["runs"] == []


async def test_closed_gateway_authority_does_not_observe_a_replacement_gateway():
    bus = MessageBus()
    old = RunStateAuthority(bus, "old-gateway")
    old.close()
    replacement = RunStateAuthority(bus, "replacement-gateway")
    await fact(bus, "new-owner", "queued")
    assert old.snapshot("websocket:chat")["runs"] == []
    assert old.snapshot("websocket:chat")["revision"] == 0
    assert replacement.snapshot("websocket:chat")["runs"][0]["run_id"] == "new-owner"
