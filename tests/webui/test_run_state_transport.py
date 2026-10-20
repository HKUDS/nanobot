"""Exercise authenticated runtime snapshots and state-only watches without sockets."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.bus.events import (
    INBOUND_META_EXECUTION_ID,
    INBOUND_META_STOP_EXECUTION_ID,
    ExecutionAdmission,
    OutboundMessage,
)
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventContext, TurnExecutionChanged
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import (
    clear_websocket_turns,
    websocket_turn_transcript_persistence_failed,
)
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.session_identity import webui_session_key


class Connection:
    def __init__(self):
        self.request = SimpleNamespace(path="/ws?client_id=client", headers=Headers())
        self.remote_address = ("127.0.0.1", 12000)
        self.sent = []
        self.closed = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def close(self, code=1000, reason=""):
        self.closed.append((code, reason))

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


@pytest.fixture
async def channel(tmp_path, monkeypatch, request):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("nanobot.webui.gateway_services.get_media_dir", lambda name: media)
    sessions = SessionManager(tmp_path)
    config = WebSocketConfig(allow_from=["client"])
    bus = MessageBus()
    gateway = build_gateway_services(
        config=config, bus=bus, session_manager=sessions, static_dist_path=None,
        workspace_path=tmp_path, default_restrict_to_workspace=True,
        config_path=tmp_path / "config.json", runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
        unified_session=getattr(request, "param", False),
    )
    ch = WebSocketChannel(config, bus, gateway=gateway)
    try:
        yield ch
    finally:
        await ch.stop()
        await sessions.state.aclose()


async def flush(channel):
    async with asyncio.timeout(3):
        while True:
            writers = tuple(state.writer for state in channel._connection_outbound.values() if state.writer)
            requests = tuple(channel._commands.request_tasks.values())
            if not writers and not requests:
                return
            await asyncio.gather(*writers, *requests)
            await asyncio.sleep(0)


async def dispatch(channel, connection, envelope, *, client_id="client"):
    await channel._dispatch_envelope(cast(Any, connection), client_id, envelope)
    await flush(channel)


async def execution(channel, owner, phase, *, chat_id="background", **kwargs):
    await channel.bus.publish(TurnExecutionChanged(
        context=RuntimeEventContext(
            channel="websocket", chat_id=chat_id, session_key=webui_session_key(chat_id),
        ), admission=ExecutionAdmission(owner), phase=phase, **kwargs,
    ))
    await flush(channel)


async def test_initial_ready_and_reconnect_attach_include_explicit_idle(channel):
    first = Connection()
    await channel._connection_loop(cast(Any, first))
    ready = first.sent[0]
    assert ready["event"] == "ready"
    assert ready["run_state_instance_id"] == channel.gateway.tokens.instance_id
    assert ready["run_state"] == {
        "instance_id": channel.gateway.tokens.instance_id, "revision": 0,
        "runs": [], "completed": [],
    }
    second = Connection()
    await dispatch(channel, second, {"type": "attach", "chat_id": ready["chat_id"]})
    attached = next(event for event in second.sent if event["event"] == "attached")
    assert attached["run_state"] == ready["run_state"]


async def test_watch_registers_idle_baseline_and_receives_no_chat_text(channel):
    connection = Connection()
    await dispatch(channel, connection, {"type": "watch_runs", "chat_ids": ["background"]})
    assert connection.sent[-1]["run_state"]["runs"] == []
    assert channel.webui_connection_chats(cast(Any, connection)) == ()
    await execution(channel, "A", "queued")
    await execution(channel, "A", "running", started_at=10)
    await channel.send(OutboundMessage(channel="websocket", chat_id="background", content="private answer"))
    await flush(channel)
    assert {event["event"] for event in connection.sent} == {"run_state"}
    assert connection.sent[-1]["run_state"]["runs"][0]["phase"] == "running"
    await dispatch(channel, connection, {"type": "watch_runs", "chat_ids": ["other"]})
    baseline_count = len(connection.sent)
    assert connection.sent[-1]["chat_id"] == "other"
    await execution(channel, "A", "exited", outcome="completed")
    assert len(connection.sent) == baseline_count
    await dispatch(channel, connection, {"type": "watch_runs", "chat_ids": ["background"]})
    assert connection.sent[-1]["run_state"]["runs"] == []
    assert connection.sent[-1]["run_state"]["completed"][0]["outcome"] == "completed"


async def test_watch_handoff_captures_changes_during_authorization(channel, monkeypatch):
    connection = Connection()
    entered, release = asyncio.Event(), asyncio.Event()
    original = channel.gateway.workspaces.async_scope_for_session_key

    async def authorize(key):
        entered.set()
        await release.wait()
        return await original(key)

    monkeypatch.setattr(channel.gateway.workspaces, "async_scope_for_session_key", authorize)
    task = asyncio.create_task(dispatch(channel, connection, {"type": "watch_runs", "chat_ids": ["background"]}))
    await asyncio.wait_for(entered.wait(), 2)
    await execution(channel, "A", "queued")
    await execution(channel, "A", "running", started_at=20)
    release.set()
    await task
    assert connection.sent[-1]["run_state"]["runs"][0]["run_id"] == "A"
    baseline_revision = connection.sent[-1]["run_state"]["revision"]
    await execution(channel, "A", "exited", outcome="cancelled")
    assert connection.sent[-1]["run_state"]["revision"] > baseline_revision
    assert connection.sent[-1]["run_state"]["runs"] == []


async def test_watch_enforces_authorization_and_temporary_chat_ownership(channel):
    owner, stranger, denied = Connection(), Connection(), Connection()
    await dispatch(channel, denied, {"type": "watch_runs", "chat_ids": ["background"]}, client_id="denied")
    assert denied.sent[-1]["detail"] == "access_denied"
    assert cast(Any, denied) not in channel._run_watches
    channel.gateway.endpoint.webui_connections.add(cast(Any, owner))
    await dispatch(channel, owner, {"type": "new_temporary_chat"})
    chat_id = owner.sent[-1]["chat_id"]
    assert owner.sent[-1]["run_state"]["runs"] == []
    await dispatch(channel, stranger, {"type": "watch_runs", "chat_ids": [chat_id]})
    assert stranger.sent[-1]["detail"] == "access_denied"
    assert cast(Any, stranger) not in channel._run_watches
    await dispatch(channel, owner, {"type": "watch_runs", "chat_ids": [chat_id]})
    assert owner.sent[-1]["run_state"]["runs"] == []
    await dispatch(channel, owner, {"type": "watch_runs", "chat_ids": ["../private"]})
    assert owner.sent[-1]["event"] == "error"
    assert channel._run_watches[cast(Any, owner)] == {chat_id}


async def test_transport_acceptance_registers_queued_root_but_not_steering_input(channel):
    connection = Connection()
    chat_id = "accepted-root"
    try:
        await dispatch(channel, connection, {
            "type": "message", "chat_id": chat_id, "webui": True,
            "turn_id": "first-input", "content": "hello",
        })
        first = channel.bus.inbound.get_nowait()
        queued = channel.gateway.runs.snapshot(webui_session_key(chat_id))
        assert queued["runs"][0]["phase"] == "queued"
        assert queued["runs"][0]["started_at"] is None
        assert queued["runs"][0]["run_id"] == first.metadata[INBOUND_META_EXECUTION_ID]
        await dispatch(channel, connection, {
            "type": "message", "chat_id": chat_id, "webui": True,
            "turn_id": "second-input", "content": "steer",
        })
        second = channel.bus.inbound.get_nowait()
        assert INBOUND_META_EXECUTION_ID not in second.metadata
        assert channel.gateway.runs.snapshot(webui_session_key(chat_id)) == queued
    finally:
        clear_websocket_turns(chat_id)


async def test_stop_request_is_correlated_cached_and_cannot_stop_new_owner(channel):
    connection = Connection()
    channel.gateway.endpoint.webui_connections.add(cast(Any, connection))
    await dispatch(channel, connection, {"type": "watch_runs", "chat_ids": ["background"]})
    await execution(channel, "A", "queued")
    await execution(channel, "A", "running", started_at=10)
    envelope = {
        "type": "webui_request", "request_id": "stop-A", "action": "runs.stop",
        "payload": {"chat_id": "background", "run_ids": ["A"]},
    }
    await dispatch(channel, connection, envelope)
    response = next(event for event in connection.sent if event["event"] == "webui_response")
    assert response["request_id"] == "stop-A" and response["ok"] is True
    assert response["result"]["run_state"]["runs"][0]["phase"] == "running"
    stop = channel.bus.inbound.get_nowait()
    assert stop.metadata[INBOUND_META_STOP_EXECUTION_ID] == "A"
    assert stop.session_key == "websocket:background"
    await execution(channel, "A", "exited", outcome="completed")
    await execution(channel, "B", "queued")
    await dispatch(channel, connection, envelope)
    assert channel.bus.inbound.empty()
    await dispatch(channel, connection, {**envelope, "request_id": "retry-A"})
    assert channel.bus.inbound.empty()
    assert channel.gateway.runs.snapshot("websocket:background")["runs"][0]["run_id"] == "B"
    await dispatch(channel, connection, {
        **envelope, "request_id": "denied-stop",
    }, client_id="denied")
    assert connection.sent[-1]["error"]["status"] == 403


async def test_execution_idle_is_independent_of_canonical_transcript_failure(channel, monkeypatch):
    from nanobot.agent.loop import AgentLoop
    from nanobot.session.webui_turns import WebuiTurnCoordinator, WebuiTurnRoutePolicy

    chat_id = "failed-transcript"
    connection = Connection()
    await dispatch(channel, connection, {"type": "watch_runs", "chat_ids": [chat_id]})
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test"
    loop = AgentLoop(
        bus=channel.bus, provider=provider,
        workspace=channel.gateway.workspaces.default_scope().project_path,
        model="test", session_manager=channel.gateway.session_manager,
    )
    loop.turn_delivery_factory.route_policy = WebuiTurnRoutePolicy(loop.sessions)
    coordinator = WebuiTurnCoordinator(channel.bus, loop.sessions, lambda coro: coro.close())
    unsubscribe = coordinator.subscribe()

    async def process(msg, **kwargs):
        return OutboundMessage(channel="websocket", chat_id=chat_id, content="answer", metadata=kwargs["delivery"].route.metadata)

    monkeypatch.setattr(loop, "_process_message", process)
    monkeypatch.setattr(channel._transcripts, "prepare_and_append", lambda *args, **kwargs: False)
    try:
        await dispatch(channel, connection, {
            "type": "message", "chat_id": chat_id, "webui": True,
            "turn_id": "turn-persistence", "content": "hello",
        })
        msg = channel.bus.inbound.get_nowait()
        await loop._dispatch_inbound(msg)
        await asyncio.gather(*loop._active_tasks[msg.session_key])
        while not channel.bus.outbound.empty():
            await channel.send(channel.bus.outbound.get_nowait())
        await flush(channel)
        snapshot = channel.gateway.runs.snapshot(msg.session_key)
        assert snapshot["runs"] == []
        assert snapshot["completed"][0]["outcome"] == "completed"
        assert websocket_turn_transcript_persistence_failed(chat_id)
        # Reconnect remains explicitly idle while legacy record safety stays unresolved.
        reconnect = Connection()
        await dispatch(channel, reconnect, {"type": "attach", "chat_id": chat_id})
        attached = next(event for event in reconnect.sent if event["event"] == "attached")
        assert attached["run_state"]["runs"] == []
    finally:
        unsubscribe()
        clear_websocket_turns(chat_id)
        await loop.aclose()


async def test_sessions_and_thread_return_independently_versioned_runtime_snapshots(channel):
    connection = Connection()
    chat_id, key = "http-run", "websocket:http-run"
    sessions = channel.gateway.session_manager
    assert sessions is not None
    await sessions.state.open_with_metadata(key, {"webui": True})
    try:
        await dispatch(channel, connection, {
            "type": "message", "chat_id": chat_id, "webui": True,
            "turn_id": "http-turn", "content": "hello",
        })
        token = channel.gateway.tokens.issue_api_token(60)
        headers = Headers({"Authorization": f"Bearer {token}"})
        unauthorized = await channel.gateway.http._handle_webui_thread_get_async(
            Request(f"/api/sessions/{key}/webui-thread", Headers()), key,
        )
        assert unauthorized.status_code == 401
        listed = await channel.gateway.http._handle_sessions_list(Request("/api/sessions", headers))
        row = next(row for row in json.loads(listed.body)["sessions"] if row["key"] == key)
        thread = await channel.gateway.http._handle_webui_thread_get_async(
            Request(f"/api/sessions/{key}/webui-thread", headers), key,
        )
        assert thread.status_code == 200
        body = json.loads(thread.body)
        assert row["run_state"] == body["run_state"] == channel.gateway.runs.snapshot(key)
        assert body["run_state"]["runs"][0]["phase"] == "queued"
        assert isinstance(body["run_state"]["revision"], int)
        assert body["run_state"]["instance_id"] == channel.gateway.tokens.instance_id
    finally:
        clear_websocket_turns(chat_id)


async def test_state_watch_uses_bounded_backpressure_without_blocking_runtime(channel, monkeypatch):
    connection = Connection()
    await dispatch(channel, connection, {"type": "watch_runs", "chat_ids": ["background"]})
    blocked = asyncio.Event()

    async def slow_send(raw):
        await blocked.wait()

    monkeypatch.setattr(connection, "send", slow_send)
    # Physical sends never hold up the execution observer, even at queue overflow.
    async with asyncio.timeout(2):
        for index in range(300):
            context = RuntimeEventContext(channel="websocket", chat_id="background", session_key="websocket:background")
            admission = ExecutionAdmission(str(index))
            await channel.bus.publish(TurnExecutionChanged(context, admission, "queued"))
            await channel.bus.publish(TurnExecutionChanged(context, admission, "exited", outcome="completed"))
    assert channel.gateway.runs.snapshot("websocket:background")["runs"] == []
    if channel._outbound_retire_tasks:
        await asyncio.gather(*tuple(channel._outbound_retire_tasks))
    assert connection.closed == [(1013, "outbound queue full")]
    assert cast(Any, connection) not in channel._run_watches


async def test_cached_stop_response_cannot_cross_temporary_chat_owners(channel):
    owner, stranger = Connection(), Connection()
    for connection in (owner, stranger):
        channel.gateway.endpoint.webui_connections.add(cast(Any, connection))
    await dispatch(channel, owner, {"type": "new_temporary_chat"})
    chat_id = owner.sent[-1]["chat_id"]
    await execution(channel, "private-owner", "queued", chat_id=chat_id)
    request = {
        "type": "webui_request", "request_id": "temporary-stop", "action": "runs.stop",
        "payload": {"chat_id": chat_id, "run_ids": ["private-owner"]},
    }
    await dispatch(channel, owner, request)
    assert owner.sent[-1]["event"] == "webui_response" and owner.sent[-1]["ok"] is True
    assert channel.bus.inbound.get_nowait().metadata[INBOUND_META_STOP_EXECUTION_ID] == "private-owner"
    await dispatch(channel, stranger, request)
    assert stranger.sent[-1]["error"]["status"] == 403
    assert "result" not in stranger.sent[-1]
    assert channel.bus.inbound.empty()


def execution_loop(channel):
    from nanobot.agent.loop import AgentLoop
    from nanobot.providers.base import GenerationSettings
    from nanobot.session.webui_turns import WebuiTurnCoordinator, WebuiTurnRoutePolicy

    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test"
    provider.provider_name = "test"
    provider.generation = GenerationSettings()
    loop = AgentLoop(
        bus=channel.bus, provider=provider,
        workspace=channel.gateway.workspaces.default_scope().project_path,
        model="test", session_manager=channel.gateway.session_manager,
        unified_session=channel.gateway.unified_session,
    )
    loop.turn_delivery_factory.route_policy = WebuiTurnRoutePolicy(loop.sessions)
    coordinator = WebuiTurnCoordinator(channel.bus, loop.sessions, lambda coro: coro.close())
    return loop, coordinator.subscribe()


async def drain_execution(loop):
    async with asyncio.timeout(3):
        while tasks := tuple(task for group in loop._active_tasks.values() for task in group):
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)


async def test_stop_during_scope_persistence_cancels_the_accepted_root(channel, monkeypatch):
    origin, other_tab = Connection(), Connection()
    channel.gateway.endpoint.webui_connections.update((cast(Any, origin), cast(Any, other_tab)))
    loop, unsubscribe = execution_loop(channel)
    entered, release = asyncio.Event(), asyncio.Event()
    persist = channel.gateway.workspaces.persist_scope
    process = AsyncMock(return_value=OutboundMessage(channel="websocket", chat_id="early-stop", content="must not run"))
    monkeypatch.setattr(loop, "_process_message", process)

    async def delayed_persist(*args, **kwargs):
        entered.set()
        await release.wait()
        return await persist(*args, **kwargs)

    monkeypatch.setattr(channel.gateway.workspaces, "persist_scope", delayed_persist)
    sending = asyncio.create_task(dispatch(channel, origin, {
        "type": "message", "chat_id": "early-stop", "webui": True,
        "turn_id": "accepted-before-persistence", "content": "hello",
    }))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        key = webui_session_key("early-stop")
        accepted = channel.gateway.runs.snapshot(key)
        owner = accepted["runs"][0]["run_id"]
        assert accepted["runs"][0]["phase"] == "queued"
        assert channel.bus.inbound.empty()
        await dispatch(channel, other_tab, {
            "type": "webui_request", "request_id": "early-stop", "action": "runs.stop",
            "payload": {"chat_id": "early-stop", "run_ids": [owner]},
        })
        response = next(event for event in other_tab.sent if event["event"] == "webui_response")
        assert response["ok"] is True
        # A request ACK is not a claim of physical exit while admission is blocked.
        assert response["result"]["run_state"]["runs"][0]["run_id"] == owner
        stop = await channel.bus.consume_inbound()
        assert stop.metadata[INBOUND_META_STOP_EXECUTION_ID] == owner
        await loop._dispatch_inbound(stop)
        release.set()
        await asyncio.wait_for(sending, 2)
        await loop._dispatch_inbound(await channel.bus.consume_inbound())
        await drain_execution(loop)
        process.assert_not_awaited()
        snapshot = channel.gateway.runs.snapshot(key)
        assert snapshot["runs"] == []
        assert snapshot["completed"] == [{
            "run_id": owner, "turn_id": "accepted-before-persistence", "outcome": "cancelled",
        }]
    finally:
        release.set()
        await asyncio.gather(sending, return_exceptions=True)
        unsubscribe()
        clear_websocket_turns("early-stop")
        await loop.aclose()


@pytest.mark.parametrize("channel", [True], indirect=True)
@pytest.mark.parametrize("stop_b", [False, True])
async def test_unified_chat_steering_relinquishes_its_provisional_owner(channel, stop_b):
    from nanobot.bus.outbound_events import TurnEndEvent
    from nanobot.providers.base import LLMResponse
    from nanobot.session.keys import UNIFIED_SESSION_KEY
    from nanobot.session.recovery import pending_followups
    from nanobot.session.webui_turns import websocket_turn_wall_started_at

    connection = Connection()
    channel.gateway.endpoint.webui_connections.add(cast(Any, connection))
    loop, unsubscribe = execution_loop(channel)
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def chat(**kwargs):
        requests.append(kwargs["messages"])
        if len(requests) == 1:
            entered.set()
            await release.wait()
        return LLMResponse(content="answer from A", finish_reason="stop")

    loop.provider.chat_stream_with_retry = chat
    try:
        await dispatch(channel, connection, {
            "type": "message", "chat_id": "unified-a", "webui": True,
            "turn_id": "turn-a", "content": "root A",
        })
        a = await channel.bus.consume_inbound()
        assert a.session_key == UNIFIED_SESSION_KEY
        await loop._dispatch_inbound(a)
        await asyncio.wait_for(entered.wait(), 2)
        await dispatch(channel, connection, {
            "type": "message", "chat_id": "unified-b", "webui": True,
            "turn_id": "turn-b", "content": "steer from B",
        })
        b = await channel.bus.consume_inbound()
        assert b.session_key == a.session_key
        owner_b = channel.gateway.runs.snapshot(webui_session_key("unified-b"))["runs"][0]["run_id"]
        await loop._dispatch_inbound(b)
        journal = await loop.sessions.state.read(UNIFIED_SESSION_KEY)
        assert journal is not None and pending_followups(journal)
        reconciled = channel.gateway.runs.snapshot(webui_session_key("unified-b"))
        assert reconciled["runs"] == []
        assert reconciled["completed"] == [{
            "run_id": owner_b, "turn_id": "turn-b", "outcome": "unknown",
        }]
        if stop_b:
            await dispatch(channel, connection, {
                "type": "webui_request", "request_id": "stop-steering", "action": "runs.stop",
                "payload": {"chat_id": "unified-b", "run_ids": [owner_b]},
            })
            # A no-longer-root steering receipt cannot cancel A or erase its journal.
            assert channel.bus.inbound.empty()
        assert channel.gateway.runs.snapshot(webui_session_key("unified-a"))["runs"][0]["phase"] == "running"
        release.set()
        await drain_execution(loop)
        assert len(requests) >= 2
        assert any("steer from B" in str(row.get("content")) for row in requests[-1])
        assert channel.gateway.runs.snapshot(webui_session_key("unified-a"))["runs"] == []
        assert channel.gateway.runs.snapshot(webui_session_key("unified-b"))["runs"] == []
        assert websocket_turn_wall_started_at("unified-b") is None
        journal = await loop.sessions.state.read(UNIFIED_SESSION_KEY)
        assert journal is not None and not pending_followups(journal)
        outbound = []
        while not channel.bus.outbound.empty():
            outbound.append(await channel.bus.consume_outbound())
        ends = [msg for msg in outbound if isinstance(msg.event, TurnEndEvent)]
        assert len(ends) == 1
        assert (ends[0].channel, ends[0].chat_id) == ("websocket", "unified-a")
        assert ends[0].metadata["webui_turn_id"] == "turn-a"
        assert all(msg.chat_id != "unified-b" for msg in outbound if msg.content == "answer from A")
    finally:
        release.set()
        unsubscribe()
        for chat_id in ("unified-a", "unified-b"):
            clear_websocket_turns(chat_id)
        await loop.aclose()


@pytest.mark.parametrize("channel", [True], indirect=True)
@pytest.mark.parametrize("entrypoint,rejection", [
    ("run", "queue_full"), ("dispatch", "conflict"), ("enqueue", "queue_full"),
])
async def test_rejected_unified_followup_retires_only_its_transport_owner(
    channel, monkeypatch, entrypoint, rejection,
):
    from nanobot.bus.outbound_events import TurnEndEvent
    from nanobot.providers.base import LLMResponse
    from nanobot.session.keys import UNIFIED_SESSION_KEY
    from nanobot.session.recovery import pending_followups
    from nanobot.session.sqlite_store import SessionConflictError
    from nanobot.session.state import SessionOperationQueueFullError
    from nanobot.session.webui_turns import websocket_turn_wall_started_at

    connection = Connection()
    channel.gateway.endpoint.webui_connections.add(cast(Any, connection))
    loop, unsubscribe = execution_loop(channel)
    entered, release = asyncio.Event(), asyncio.Event()
    failure_entered, failure_release = asyncio.Event(), asyncio.Event()
    requests = []
    consumer = None
    error_type = SessionOperationQueueFullError if rejection == "queue_full" else SessionConflictError
    queue_followup = loop.sessions.state.queue_followup
    publish_outbound = channel.bus.publish_outbound

    async def chat(**kwargs):
        requests.append(kwargs["messages"])
        if len(requests) == 1:
            entered.set()
            await release.wait()
        return LLMResponse(content="answer from A", finish_reason="stop")

    async def reject_followup(key, msg):
        if msg.content == "rejected from B":
            raise error_type("follow-up storage admission rejected")
        return await queue_followup(key, msg)

    async def block_failure_write(msg):
        if msg.content == "Sorry, I encountered an error.":
            failure_entered.set()
            await failure_release.wait()
        await publish_outbound(msg)

    loop.provider.chat_stream_with_retry = chat
    monkeypatch.setattr(loop.sessions.state, "queue_followup", reject_followup)
    monkeypatch.setattr(channel.bus, "publish_outbound", block_failure_write)
    try:
        await dispatch(channel, connection, {
            "type": "message", "chat_id": "rejection-a", "webui": True,
            "turn_id": "turn-a", "content": "root A",
        })
        a = await channel.bus.consume_inbound()
        await loop._dispatch_inbound(a)
        await asyncio.wait_for(entered.wait(), 2)
        active_a = channel.gateway.runs.snapshot(webui_session_key("rejection-a"))
        await dispatch(channel, connection, {
            "type": "message", "chat_id": "rejection-a", "webui": True,
            "turn_id": "steering-a", "content": "keep this steering",
        })
        await loop._dispatch_inbound(await channel.bus.consume_inbound())
        journal = await loop.sessions.state.read(UNIFIED_SESSION_KEY)
        assert journal is not None
        kept = pending_followups(journal)
        assert [msg.content for msg in kept] == ["keep this steering"]
        await dispatch(channel, connection, {
            "type": "message", "chat_id": "rejection-b", "webui": True,
            "turn_id": "turn-b", "content": "rejected from B",
        })
        owner_b = channel.gateway.runs.snapshot(webui_session_key("rejection-b"))["runs"][0]["run_id"]
        if entrypoint == "run":
            consumer = asyncio.create_task(loop.run())
            await asyncio.wait_for(failure_entered.wait(), 2)
        else:
            b = await channel.bus.consume_inbound()
            admit = loop._dispatch_inbound if entrypoint == "dispatch" else loop._enqueue_session_message
            with pytest.raises(error_type, match="storage admission rejected"):
                await admit(b)
        # Rejection is terminal before the failure response can block or fail.
        snapshot = channel.gateway.runs.snapshot(webui_session_key("rejection-b"))
        assert snapshot["runs"] == []
        assert snapshot["completed"] == [{
            "run_id": owner_b, "turn_id": "turn-b", "outcome": "failed",
        }]
        assert websocket_turn_wall_started_at("rejection-b") is None
        preserved_a = channel.gateway.runs.snapshot(webui_session_key("rejection-a"))
        assert preserved_a["runs"] == active_a["runs"]
        assert preserved_a["completed"] == active_a["completed"]
        assert websocket_turn_wall_started_at("rejection-a") is not None
        journal = await loop.sessions.state.read(UNIFIED_SESSION_KEY)
        assert journal is not None and pending_followups(journal) == kept
        assert loop._pending_queues[UNIFIED_SESSION_KEY].qsize() == 1
        await dispatch(channel, connection, {
            "type": "webui_request", "request_id": "stop-rejected", "action": "runs.stop",
            "payload": {"chat_id": "rejection-b", "run_ids": [owner_b]},
        })
        assert channel.bus.inbound.empty()
        failure_release.set()
        release.set()
        await drain_execution(loop)
        assert any("keep this steering" in str(row.get("content")) for row in requests[-1])
        assert not any("rejected from B" in str(row.get("content")) for row in requests[-1])
        journal = await loop.sessions.state.read(UNIFIED_SESSION_KEY)
        assert journal is not None and not pending_followups(journal)
        ends = []
        while not channel.bus.outbound.empty():
            msg = await channel.bus.consume_outbound()
            if isinstance(msg.event, TurnEndEvent):
                ends.append(msg.chat_id)
        assert ends == ["rejection-a"]
    finally:
        failure_release.set()
        release.set()
        if consumer is not None:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
        await loop.aclose()
        unsubscribe()
        for chat_id in ("rejection-a", "rejection-b"):
            clear_websocket_turns(chat_id)


@pytest.mark.parametrize("channel", [True], indirect=True)
@pytest.mark.parametrize("content,reply", [
    ("/help extra", 'Command "/help" does not accept arguments.'),
    ("/help\textra", 'Command "/help" does not accept arguments.'),
    ("/__shell pwd", "Shell commands are only available from a trusted local client."),
])
async def test_inline_control_does_not_reserve_a_unified_execution_owner(
    channel, monkeypatch, content, reply,
):
    from nanobot.session.webui_turns import websocket_turn_wall_started_at

    connection = Connection()
    loop, unsubscribe = execution_loop(channel)
    entered, release = asyncio.Event(), asyncio.Event()

    async def process(msg, **kwargs):
        entered.set()
        await release.wait()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="answer from A")

    monkeypatch.setattr(loop, "_process_message", process)
    try:
        await dispatch(channel, connection, {
            "type": "message", "chat_id": "inline-a", "webui": True,
            "turn_id": "turn-a", "content": "root A",
        })
        await loop._dispatch_inbound(await channel.bus.consume_inbound())
        await asyncio.wait_for(entered.wait(), 2)
        active_a = channel.gateway.runs.snapshot(webui_session_key("inline-a"))
        await dispatch(channel, connection, {
            "type": "message", "chat_id": "inline-b", "webui": True,
            "turn_id": "turn-b", "content": content,
        })
        assert channel.gateway.runs.snapshot(webui_session_key("inline-b"))["runs"] == []
        b = await channel.bus.consume_inbound()
        assert b.execution_admission is None
        await loop._dispatch_inbound(b)
        assert channel.gateway.runs.snapshot(webui_session_key("inline-b"))["runs"] == []
        assert websocket_turn_wall_started_at("inline-b") is None
        assert channel.gateway.runs.snapshot(webui_session_key("inline-a")) == active_a
        assert loop._pending_queues[b.session_key].empty()
        responses = []
        while not channel.bus.outbound.empty():
            responses.append(await channel.bus.consume_outbound())
        assert any(msg.chat_id == "inline-b" and msg.content.startswith(reply) for msg in responses)
    finally:
        release.set()
        await drain_execution(loop)
        unsubscribe()
        for chat_id in ("inline-a", "inline-b"):
            clear_websocket_turns(chat_id)
        await loop.aclose()
