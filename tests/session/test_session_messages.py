from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.tools.session_messages import SendSessionMessageTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import SessionMessageInputEvent
from nanobot.bus.queue import MessageBus
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import SessionHandle, SessionHandleDirectory
from nanobot.session.session_messages import (
    SESSION_MESSAGE_METADATA_KEY,
    SESSION_REPLY_TIMEOUT_METADATA_KEY,
    SessionMessageError,
    session_message_envelope,
    session_message_inbound,
    session_reply_timeout_envelope,
    session_reply_timeout_inbound,
)
from nanobot.session.webui_turns import project_session_message_input
from nanobot.webui.transcript import read_transcript_lines


class _FakeTimer:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[float, Callable[[], None], _FakeTimer]] = []

    def __call__(self, delay: float, callback: Callable[[], None]) -> _FakeTimer:
        timer = _FakeTimer()
        self.calls.append((delay, callback, timer))
        return timer


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSessionHandleDirectory:
    def __init__(self, identities: list[SessionHandle]) -> None:
        self._by_key = {identity.session_key: identity for identity in identities}
        self._by_name = {identity.name.casefold(): identity for identity in identities}

    def ensure(self, session_key: str) -> SessionHandle:
        identity = self.handle_for_session(session_key)
        if identity is None:
            raise ValueError(f"unknown session: {session_key}")
        return identity

    def resolve(self, name: str) -> SessionHandle | None:
        return self._by_name.get(name.casefold())

    def handle_for_session(self, key: str) -> SessionHandle | None:
        return self._by_key.get(key)


def _identity(name: str, session_key: str, workspace: Path) -> SessionHandle:
    color_slot = 1 if name == "lead" else 2
    return SessionHandle(
        id=f"handle_{color_slot:032x}",
        name=name,
        color_slot=color_slot,
        session_key=session_key,
        workspace=workspace,
    )


def _persist(sessions: SessionManager, key: str) -> None:
    session = sessions.get_or_create(key)
    session.metadata["webui"] = True
    sessions.save(session)


def _service(
    tmp_path: Path,
    *,
    max_messages_per_minute: int = 6,
    schedule_later: Callable[[float, Callable[[], None]], _FakeTimer] | None = None,
    clock: Callable[[], float] | None = None,
) -> tuple[SendSessionMessageTool, MessageBus, SessionManager]:
    workspace = tmp_path / "project"
    workspace.mkdir(exist_ok=True)
    sessions = SessionManager(tmp_path / "state")
    source = _identity("lead", "websocket:lead", workspace)
    target = _identity("reviewer", "websocket:reviewer", workspace)
    for identity in (source, target):
        _persist(sessions, identity.session_key)
    sessions.invalidate(source.session_key)
    sessions.invalidate(target.session_key)
    bus = MessageBus()
    return (
        SendSessionMessageTool(
            sessions=sessions,
            bus=bus,
            directory=FakeSessionHandleDirectory([source, target]),
            max_messages_per_minute=max_messages_per_minute,
            schedule_later=schedule_later,
            clock=clock,
        ),
        bus,
        sessions,
    )


@pytest.mark.asyncio
async def test_webui_input_is_persisted_and_projected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.transcript.get_webui_dir", lambda: tmp_path / "webui")
    service, bus, _sessions = _service(tmp_path)

    target_handle = await service.enqueue(
        source_session_key="websocket:lead",
        target_handle="@reviewer",
        content="Review the implementation.",
        expect_reply=True,
        reply_timeout_seconds=60,
    )

    assert target_handle == "@reviewer"
    inbound = bus.inbound.get_nowait()
    assert inbound.channel == "websocket"
    assert inbound.sender_id == "session"
    assert inbound.chat_id == "reviewer"
    assert inbound.session_key_override == "websocket:reviewer"
    assert inbound.require_existing_session is True
    assert inbound.content == "Review the implementation."
    assert set(inbound.metadata) == {SESSION_MESSAGE_METADATA_KEY}
    envelope = session_message_envelope(inbound.metadata)
    assert envelope is not None
    assert session_message_inbound(inbound) == envelope
    message_id = envelope["message_id"]
    assert envelope["expect_reply"] is True
    assert set(envelope) == {
        "message_id",
        "created_at_ms",
        "expect_reply",
        "source",
        "target",
    }
    assert envelope["source"] == {
        "name": "lead",
        "session_key": "websocket:lead",
        "handle_id": "handle_00000000000000000000000000000001",
        "color_slot": 1,
    }
    assert envelope["target"] == {
        "name": "reviewer",
        "session_key": "websocket:reviewer",
    }
    assert bus.outbound.empty()

    await project_session_message_input(bus, inbound, "websocket:reviewer")

    live = bus.outbound.get_nowait()
    assert (live.channel, live.chat_id) == ("websocket", "reviewer")
    assert isinstance(live.event, SessionMessageInputEvent)
    assert live.event.content == "Review the implementation."
    assert live.event.session_message == {
        "direction": "incoming",
        "message_id": message_id,
        "session": {
            "id": "handle_00000000000000000000000000000001",
            "name": "lead",
            "color_slot": 1,
        },
    }
    assert "websocket:" not in str(live.event.session_message)
    assert bus.outbound.empty()
    transcript = read_transcript_lines("websocket:reviewer")
    assert len(transcript) == 1
    assert transcript[0]["text"] == "Review the implementation."
    assert transcript[0]["session_message"] == live.event.session_message


@pytest.mark.asyncio
async def test_projection_publishes_when_transcript_persistence_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.transcript.get_webui_dir", lambda: tmp_path / "webui")
    service, bus, _sessions = _service(tmp_path)
    await service.enqueue(
        source_session_key="websocket:lead",
        target_handle="@reviewer",
        content="Review the implementation.",
        expect_reply=False,
    )
    inbound = bus.inbound.get_nowait()
    attempts = 0

    def fail_append(*args: object, **kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("write failed")

    monkeypatch.setattr(
        "nanobot.session.webui_turns.append_session_message_input",
        fail_append,
    )

    await project_session_message_input(bus, inbound, "websocket:reviewer")

    assert attempts == 1
    assert bus.outbound.qsize() == 1
    assert read_transcript_lines("websocket:reviewer") == []


@pytest.mark.asyncio
async def test_enqueue_accepts_persisted_target_that_is_not_cached(tmp_path: Path) -> None:
    service, bus, sessions = _service(tmp_path)
    assert sessions.get_cached("websocket:reviewer") is None

    await service.enqueue(
        source_session_key="websocket:lead",
        target_handle="reviewer",
        content="Ping",
        expect_reply=False,
    )

    assert bus.inbound_size == 1
    assert sessions.get_cached("websocket:reviewer") is None


@pytest.mark.asyncio
async def test_enqueue_supports_non_webui_sessions(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    sessions = SessionManager(tmp_path / "state")
    source_key = "telegram:source"
    source = sessions.get_or_create(source_key)
    source.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {
        "project_path": str(workspace),
        "access_mode": "restricted",
    }
    sessions.save(source)
    target_key = "telegram:target"
    target_session = sessions.get_or_create(target_key)
    target_session.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {
        "project_path": str(workspace),
        "access_mode": "restricted",
    }
    sessions.save(target_session)
    directory = SessionHandleDirectory(sessions)
    target = directory.ensure_many([target_key])[target_key]
    bus = MessageBus()
    service = SendSessionMessageTool(
        sessions=sessions,
        bus=bus,
        directory=directory,
    )

    await service.enqueue(
        source_session_key=source_key,
        target_handle=target.name,
        content="Ping",
        expect_reply=False,
    )

    inbound = bus.inbound.get_nowait()
    envelope = session_message_inbound(inbound)
    assert envelope is not None
    assert envelope["source"]["session_key"] == source_key
    assert envelope["target"]["session_key"] == target_key
    assert directory.handle_for_session(source_key) is not None

@pytest.mark.asyncio
async def test_enqueue_uses_persistent_session_handles(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    sessions = SessionManager(tmp_path / "state")
    for key, title in (
        ("websocket:lead", "Lead"),
        ("websocket:reviewer", "Reviewer"),
    ):
        session = sessions.get_or_create(key)
        session.metadata.update({
            "title": title,
            "webui": True,
            WORKSPACE_SCOPE_METADATA_KEY: {
                "project_path": str(workspace),
                "access_mode": "restricted",
            },
        })
        sessions.save(session)
    directory = SessionHandleDirectory(sessions)
    handles = directory.ensure_many(["websocket:lead", "websocket:reviewer"])
    source = handles["websocket:lead"]
    target = handles["websocket:reviewer"]
    bus = MessageBus()
    service = SendSessionMessageTool(sessions=sessions, bus=bus, directory=directory)

    target_handle = await service.enqueue(
        source_session_key=source.session_key,
        target_handle=f"@{target.name}",
        content="Please review this.",
        expect_reply=True,
        reply_timeout_seconds=60,
    )

    assert target_handle == f"@{target.name}"
    inbound = bus.inbound.get_nowait()
    envelope = session_message_envelope(inbound.metadata)
    assert envelope is not None
    assert envelope["source"]["handle_id"] == source.id
    assert envelope["target"]["session_key"] == target.session_key


@pytest.mark.asyncio
async def test_enqueue_rejects_stale_target_before_bus_mutation(tmp_path: Path) -> None:
    service, bus, sessions = _service(tmp_path)
    sessions.delete_session("websocket:reviewer")

    with pytest.raises(SessionMessageError, match="not persisted") as exc_info:
        await service.enqueue(
            source_session_key="websocket:lead",
            target_handle="reviewer",
            content="Ping",
            expect_reply=False,
        )

    assert exc_info.value.code == "target_not_found"
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_enqueue_allows_self_send(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    sessions = SessionManager(tmp_path / "state")
    source = _identity("lead", "websocket:lead", workspace)
    _persist(sessions, source.session_key)
    bus = MessageBus()
    service = SendSessionMessageTool(
        sessions=sessions,
        bus=bus,
        directory=FakeSessionHandleDirectory([source]),
    )

    await service.enqueue(
        source_session_key=source.session_key,
        target_handle="@lead",
        content="Loop",
        expect_reply=False,
    )

    assert bus.inbound_size == 1


@pytest.mark.asyncio
async def test_enqueue_accepts_cross_workspace_target(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    other = tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    sessions = SessionManager(tmp_path / "state")
    source = _identity("lead", "websocket:lead", workspace)
    target = _identity("reviewer", "websocket:reviewer", other)
    for identity in (source, target):
        _persist(sessions, identity.session_key)

    bus = MessageBus()
    scheduler = _FakeScheduler()
    service = SendSessionMessageTool(
        sessions=sessions,
        bus=bus,
        directory=FakeSessionHandleDirectory([source, target]),
        schedule_later=scheduler,
    )

    await service.enqueue(
        source_session_key=source.session_key,
        target_handle="reviewer",
        content="Ping",
        expect_reply=True,
        reply_timeout_seconds=60,
    )

    inbound = bus.inbound.get_nowait()
    envelope = session_message_inbound(inbound)
    assert envelope is not None
    assert envelope["source"]["session_key"] == source.session_key
    assert envelope["target"]["session_key"] == target.session_key

    scheduler.calls[0][1]()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    timeout = bus.inbound.get_nowait()
    assert session_reply_timeout_inbound(timeout) is not None


@pytest.mark.asyncio
async def test_enqueue_enforces_per_session_minute_limit(tmp_path: Path) -> None:
    clock = _FakeClock()
    service, bus, _sessions = _service(
        tmp_path,
        max_messages_per_minute=2,
        clock=clock,
    )
    for index in range(2):
        await service.enqueue(
            source_session_key="websocket:lead",
            target_handle="reviewer",
            content=f"Ping {index}",
            expect_reply=False,
        )

    with pytest.raises(SessionMessageError) as exc_info:
        await service.enqueue(
            source_session_key="websocket:lead",
            target_handle="reviewer",
            content="Too many",
            expect_reply=False,
        )
    assert exc_info.value.code == "rate_limited"

    await service.enqueue(
        source_session_key="websocket:reviewer",
        target_handle="lead",
        content="Independent sender",
        expect_reply=False,
    )
    clock.advance(60)
    await service.enqueue(
        source_session_key="websocket:lead",
        target_handle="reviewer",
        content="New window",
        expect_reply=False,
    )
    assert bus.inbound_size == 4


@pytest.mark.asyncio
async def test_enqueue_publish_failure_does_not_consume_rate_limit(
    tmp_path: Path,
) -> None:
    service, bus, _sessions = _service(tmp_path, max_messages_per_minute=1)
    original_publish = bus.publish_inbound
    bus.publish_inbound = AsyncMock(side_effect=RuntimeError("bus unavailable"))

    with pytest.raises(RuntimeError, match="bus unavailable"):
        await service.enqueue(
            source_session_key="websocket:lead",
            target_handle="reviewer",
            content="first attempt",
            expect_reply=False,
        )

    bus.publish_inbound = original_publish
    target_handle = await service.enqueue(
        source_session_key="websocket:lead",
        target_handle="reviewer",
        content="retry",
        expect_reply=False,
    )
    assert target_handle == "@reviewer"
    assert bus.inbound_size == 1


@pytest.mark.asyncio
async def test_enqueue_requires_timeout_only_for_requested_replies(tmp_path: Path) -> None:
    service, bus, _sessions = _service(tmp_path)

    with pytest.raises(SessionMessageError) as exc_info:
        await service.enqueue(
            source_session_key="websocket:lead",
            target_handle="reviewer",
            content="Please reply",
            expect_reply=True,
        )
    assert exc_info.value.code == "invalid_reply_timeout"

    with pytest.raises(SessionMessageError) as exc_info:
        await service.enqueue(
            source_session_key="websocket:lead",
            target_handle="reviewer",
            content="Please reply",
            expect_reply=True,
            reply_timeout_seconds=61,
        )
    assert exc_info.value.code == "invalid_reply_timeout"

    with pytest.raises(SessionMessageError) as exc_info:
        await service.enqueue(
            source_session_key="websocket:lead",
            target_handle="reviewer",
            content="No reply needed",
            expect_reply=False,
            reply_timeout_seconds=60,
        )
    assert exc_info.value.code == "unexpected_reply_timeout"
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_requested_reply_timeout_resumes_the_waiting_session(tmp_path: Path) -> None:
    scheduler = _FakeScheduler()
    service, bus, _sessions = _service(tmp_path, schedule_later=scheduler)

    await service.enqueue(
        source_session_key="websocket:lead",
        target_handle="reviewer",
        content="Please reply",
        expect_reply=True,
        reply_timeout_seconds=60,
    )
    bus.inbound.get_nowait()
    assert len(scheduler.calls) == 1
    delay, expire, timer = scheduler.calls[0]
    assert delay == 60
    assert timer.cancelled is False

    expire()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    timeout_message = bus.inbound.get_nowait()
    timeout = session_reply_timeout_envelope(timeout_message.metadata)
    assert timeout is not None
    assert session_reply_timeout_inbound(timeout_message) == timeout
    assert timeout["timeout_seconds"] == 60
    assert timeout["source"]["session_key"] == "websocket:lead"
    assert timeout["target"]["session_key"] == "websocket:reviewer"


@pytest.mark.asyncio
async def test_session_reply_cancels_its_pending_timeout(tmp_path: Path) -> None:
    scheduler = _FakeScheduler()
    service, bus, _sessions = _service(tmp_path, schedule_later=scheduler)

    await service.enqueue(
        source_session_key="websocket:lead",
        target_handle="reviewer",
        content="Please reply",
        expect_reply=True,
        reply_timeout_seconds=60,
    )
    bus.inbound.get_nowait()
    timer = scheduler.calls[0][2]

    await service.enqueue(
        source_session_key="websocket:reviewer",
        target_handle="lead",
        content="Here is the answer",
        expect_reply=False,
    )

    assert timer.cancelled is True
    reply = bus.inbound.get_nowait()
    assert session_message_inbound(reply) is not None


@pytest.mark.asyncio
async def test_new_reply_wait_replaces_the_previous_wait_for_the_same_session_pair(
    tmp_path: Path,
) -> None:
    scheduler = _FakeScheduler()
    service, bus, _sessions = _service(tmp_path, schedule_later=scheduler)

    await service.enqueue(
        source_session_key="websocket:reviewer",
        target_handle="lead",
        content="First question",
        expect_reply=True,
        reply_timeout_seconds=60,
    )
    await service.enqueue(
        source_session_key="websocket:reviewer",
        target_handle="lead",
        content="Second question",
        expect_reply=True,
        reply_timeout_seconds=30,
    )

    assert bus.inbound_size == 2
    assert len(scheduler.calls) == 2
    assert scheduler.calls[0][2].cancelled is True
    assert scheduler.calls[1][2].cancelled is False

    scheduler.calls[0][1]()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert bus.inbound_size == 2


def test_session_message_envelope_rejects_dynamic_boundary_violations() -> None:
    assert session_message_envelope(None) is None
    assert session_message_envelope({SESSION_MESSAGE_METADATA_KEY: {}}) is None

    metadata = _session_message_metadata()
    envelope = metadata[SESSION_MESSAGE_METADATA_KEY]
    assert isinstance(envelope, dict)
    envelope.pop("expect_reply")
    assert session_message_envelope(metadata) is None

    metadata = _session_message_metadata()
    envelope = metadata[SESSION_MESSAGE_METADATA_KEY]
    assert isinstance(envelope, dict)
    envelope["expect_reply"] = 1
    assert session_message_envelope(metadata) is None


def test_session_inbound_checks_sender_and_route_not_lifecycle_policy() -> None:
    metadata = _session_message_metadata()
    internal = InboundMessage(
        channel="system",
        sender_id="session",
        chat_id="websocket:reviewer",
        content="Review this",
        metadata=metadata,
        session_key_override="websocket:reviewer",
    )
    forged = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="reviewer",
        content="/stop",
        metadata=metadata,
        session_key_override="websocket:reviewer",
        require_existing_session=True,
    )
    wrong_target = InboundMessage(
        channel="system",
        sender_id="session",
        chat_id="websocket:other",
        content="/stop",
        metadata=metadata,
        session_key_override="websocket:other",
        require_existing_session=True,
    )

    assert session_message_inbound(internal) is not None
    assert session_message_inbound(forged) is None
    assert session_message_inbound(wrong_target) is None


def test_session_reply_timeout_checks_sender_and_route_not_lifecycle_policy() -> None:
    metadata = _session_message_metadata()
    request = metadata[SESSION_MESSAGE_METADATA_KEY]
    assert isinstance(request, dict)
    timeout_metadata = {
        SESSION_REPLY_TIMEOUT_METADATA_KEY: {
            **request,
            "timeout_seconds": 60,
        },
    }
    internal = InboundMessage(
        channel="system",
        sender_id="session_timeout",
        chat_id="websocket:lead",
        content="",
        metadata=timeout_metadata,
        session_key_override="websocket:lead",
    )
    forged = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="lead",
        content="",
        metadata=timeout_metadata,
        session_key_override="websocket:lead",
        require_existing_session=True,
    )

    assert session_reply_timeout_envelope(timeout_metadata) is not None
    assert session_reply_timeout_inbound(internal) is not None
    assert session_reply_timeout_inbound(forged) is None

    request["expect_reply"] = False
    assert session_reply_timeout_envelope({
        SESSION_REPLY_TIMEOUT_METADATA_KEY: {
            **request,
            "timeout_seconds": 60,
        },
    }) is None


def _session_message_metadata() -> dict[str, object]:
    return {
        SESSION_MESSAGE_METADATA_KEY: {
            "message_id": "message-1",
            "created_at_ms": 1,
            "expect_reply": True,
            "source": {
                "name": "lead",
                "session_key": "websocket:lead",
                "handle_id": "handle_00000000000000000000000000000001",
                "color_slot": 1,
            },
            "target": {
                "name": "reviewer",
                "session_key": "websocket:reviewer",
            },
        }
    }
