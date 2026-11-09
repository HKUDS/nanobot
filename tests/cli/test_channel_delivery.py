from functools import partial

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.cli.gateway_runtime import _deliver_to_channel
from nanobot.session.display_history import HISTORY_GENERATION_METADATA_KEY
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services


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


@pytest.fixture
async def webui_delivery(delivery, tmp_path, monkeypatch):
    sessions, bus, tool = delivery
    data = tmp_path / "instance"
    data.mkdir()
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: data)
    config = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"], "host": "127.0.0.1", "port": 0,
    })
    gateway = build_gateway_services(
        config=config, bus=bus, session_manager=sessions, static_dist_path=None,
        workspace_path=sessions.workspace, default_restrict_to_workspace=True,
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None,
        config_path=data / "config.json",
    )
    return sessions, bus, tool, WebSocketChannel(config, bus, gateway=gateway)


@pytest.mark.parametrize("caption", ["caption", ""])
async def test_unified_webui_media_keeps_its_display_generation(webui_delivery, caption):
    sessions, bus, tool, channel = webui_delivery
    alias = await sessions.state.get_header("websocket:chat")
    canonical = await sessions.state.get_header(UNIFIED_SESSION_KEY)
    tool.set_send_callback(partial(
        _deliver_to_channel, bus=bus, session_manager=sessions, unified_session=True,
    ))
    with request_context(RequestContext(
        "websocket", "chat", session_key=canonical.key,
        session_generation=canonical.generation,
        metadata={HISTORY_GENERATION_METADATA_KEY: alias.generation},
    )):
        result = await tool.execute(content=caption, media=["attachment.txt"])

    assert result == "Message sent to websocket:chat with 1 attachments"
    sent = bus.outbound.get_nowait()
    assert sent.metadata[HISTORY_GENERATION_METADATA_KEY] == alias.generation
    await channel.send(sent)
    facts = await sessions.state.project_history(alias.key, lambda history: history.all_facts())
    assert len(facts) == 1
    assert facts[0].content["text"] == caption
    assert facts[0].content["media"] == sent.media


async def test_cross_channel_text_is_saved_in_webui_history(webui_delivery):
    sessions, bus, tool, channel = webui_delivery
    alias = await sessions.state.get_header("websocket:chat")
    source = await sessions.state.get_header("telegram:origin")
    with request_context(RequestContext(
        "telegram", "origin", session_key=source.key, session_generation=source.generation,
    )):
        result = await tool.execute(content="notice", channel="websocket", chat_id="chat")

    assert result == "Message sent to websocket:chat"
    sent = bus.outbound.get_nowait()
    await channel.send(sent)
    facts = await sessions.state.project_history(alias.key, lambda history: history.all_facts())
    assert [fact.content["text"] for fact in facts] == ["notice"]


@pytest.mark.parametrize("operation", ["reset", "delete"])
async def test_webui_destination_revocation_after_admission_blocks_history(
    webui_delivery, monkeypatch, operation,
):
    sessions, bus, tool, channel = webui_delivery
    target = await sessions.state.get_header("websocket:chat")
    original = bus.publish_outbound

    async def revoke_before_enqueue(message):
        assert message.metadata[HISTORY_GENERATION_METADATA_KEY] == target.generation
        await getattr(sessions.state, operation)(target.key)
        await original(message)

    monkeypatch.setattr(bus, "publish_outbound", revoke_before_enqueue)
    result = await tool.execute(content="late notice", channel="websocket", chat_id="chat")
    assert result == "Message sent to websocket:chat"
    await channel.send(bus.outbound.get_nowait())
    assert await sessions.state.project_history(target.key, lambda history: history.all_facts()) == []
    current = await sessions.state.read(target.key)
    assert current is None or current.generation != target.generation


@pytest.mark.parametrize("media", [None, ["attachment.txt"]])
async def test_direct_webui_send_does_not_create_a_missing_destination(webui_delivery, media):
    sessions, bus, tool, _ = webui_delivery
    result = await tool.execute(
        content="notice", channel="websocket", chat_id="missing", media=media,
    )
    assert result.startswith("Error sending message:")
    assert bus.outbound.empty()
    assert await sessions.state.read("websocket:missing") is None


async def test_temporary_webui_media_stays_nonpersistent(webui_delivery):
    sessions, bus, tool, channel = webui_delivery
    target = await sessions.state.register_transient("websocket:temporary")
    with request_context(RequestContext(
        "websocket", "temporary", session_key=target.key,
        session_generation=target.generation,
        metadata={HISTORY_GENERATION_METADATA_KEY: target.generation},
    )):
        result = await tool.execute(content="caption", media=["attachment.txt"])
    assert result == "Message sent to websocket:temporary with 1 attachments"
    await channel.send(bus.outbound.get_nowait())
    assert await sessions.state.project_history(target.key, lambda history: history.revision) is None
