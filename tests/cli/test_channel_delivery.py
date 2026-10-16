"""Message tools preserve target identity through gateway delivery recording."""

from functools import partial

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.queue import MessageBus
from nanobot.cli.gateway_runtime import _deliver_to_channel
from nanobot.session.manager import SessionManager


@pytest.fixture
async def delivery(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "attachment.txt").write_text("attachment", encoding="utf-8")
    sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    bus = MessageBus()
    tool = MessageTool(
        send_callback=partial(_deliver_to_channel, bus=bus, session_manager=sessions),
        workspace=workspace,
    )
    try:
        yield sessions, bus, tool
    finally:
        await sessions.state.aclose()


@pytest.mark.parametrize("channel,chat_id,key,metadata", [
    ("slack", "C123", "slack:C123:111.222", {"slack": {"thread_ts": "111.222"}}),
    ("telegram", "-100123", "telegram:-100123:topic:42", {"message_thread_id": 42}),
])
async def test_thread_media_is_recorded_in_its_admitted_session(delivery, channel, chat_id, key, metadata):
    sessions, bus, tool = delivery
    session = await sessions.state.get(key)
    coarse_key = f"{channel}:{chat_id}"
    await sessions.state.get(coarse_key)
    with request_context(RequestContext(
        channel, chat_id, session_key=key, session_generation=session.generation, metadata=metadata,
    )):
        result = await tool.execute(content="caption", media=["attachment.txt"])

    assert result == f"Message sent to {channel}:{chat_id} with 1 attachments"
    sent = bus.outbound.get_nowait()
    assert sent.metadata == metadata
    assert len(sent.media) == 1
    assert [message["content"] for message in (await sessions.state.read(key)).messages] == ["caption"]
    assert (await sessions.state.read(coarse_key)).messages == []


async def test_first_cross_target_media_creates_its_own_session(delivery):
    sessions, bus, tool = delivery
    origin = await sessions.state.get("websocket:origin")
    with request_context(RequestContext(
        "websocket", "origin", session_key=origin.key, session_generation=origin.generation,
    )):
        result = await tool.execute(
            content="caption", channel="email", chat_id="fresh@example.invalid",
            media=["attachment.txt"],
        )

    assert result == "Message sent to email:fresh@example.invalid with 1 attachments"
    sent = bus.outbound.get_nowait()
    assert sent.metadata == {}
    target = await sessions.state.read("email:fresh@example.invalid")
    assert [message["content"] for message in target.messages] == ["caption"]
    assert (await sessions.state.read(origin.key)).messages == []


@pytest.mark.parametrize("operation", ["reset", "delete"])
async def test_old_turn_media_cannot_recreate_or_write_a_replaced_target(delivery, operation):
    sessions, bus, tool = delivery
    session = await sessions.state.get("slack:C123:111.222")
    await getattr(sessions.state, operation)(session.key)
    with request_context(RequestContext(
        "slack", "C123", session_key=session.key, session_generation=session.generation,
    )):
        result = await tool.execute(content="late caption", media=["attachment.txt"])

    assert result.startswith("Error sending message:")
    assert bus.outbound.empty()
    target = await sessions.state.read(session.key)
    assert target is None or target.messages == []
    assert await sessions.state.read("slack:C123") is None


async def test_cross_target_reset_after_admission_revokes_media(delivery, monkeypatch):
    sessions, bus, tool = delivery
    original = sessions.state.record_delivery

    async def reset_before_recording(key, *args, **kwargs):
        await sessions.state.reset(key)
        await original(key, *args, **kwargs)

    monkeypatch.setattr(sessions.state, "record_delivery", reset_before_recording)
    result = await tool.execute(
        content="late caption", channel="email", chat_id="fresh@example.invalid",
        media=["attachment.txt"],
    )
    assert "replaced session" in result
    assert bus.outbound.empty()
    assert (await sessions.state.read("email:fresh@example.invalid")).messages == []
