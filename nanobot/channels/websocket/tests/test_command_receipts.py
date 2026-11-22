from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.command.builtin import cmd_dream_log, cmd_model, cmd_skill, cmd_stop
from nanobot.command.results import command_reply, line, message_text
from nanobot.command.router import CommandContext
from nanobot.session.display_history import MAX_HISTORY_FACT_BYTES, HistoryFact, HistoryKind
from nanobot.utils.gitstore import CommitInfo

from .test_websocket_channel import _basic_handler, _sent_ws_payloads
from .test_websocket_media_route import _fake_media_dir


@pytest.fixture
async def chat(history):
    bus = MessageBus()
    gateway = _basic_handler(bus, session_manager=history.sessions, workspace_path=history.sessions.workspace)
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=gateway)
    connection = AsyncMock()
    channel._attach(connection, "chat")
    try:
        yield channel, connection
    finally:
        await channel._cleanup_connection(connection)


@pytest.mark.parametrize("raw", ["/skill", "/SKILL@nanobot list"])
async def test_ui_skill_list_rejected_before_dispatch_but_skill_reference_is_sent(chat, raw):
    channel, connection = chat
    envelope = {"type": "message", "chat_id": "chat", "webui": True}
    await channel._dispatch_envelope(connection, "user", {**envelope, "turn_id": "list", "content": raw})
    rejection, = _sent_ws_payloads(connection)
    assert (rejection["event"], rejection["detail"], rejection["turn_id"]) == ("error", "message_rejected", "list")
    assert channel.bus.inbound_size == 0
    await channel._dispatch_envelope(connection, "user", {**envelope, "turn_id": "use", "content": "$weather Tokyo"})
    assert channel.bus.inbound_size == 1
    assert (await channel.bus.consume_inbound()).content == "$weather Tokyo"


async def _command(history, raw):
    msg = InboundMessage("websocket", "user", "chat", raw, metadata=await history.metadata("chat"))
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, loop=MagicMock())


async def test_ui_silences_only_successful_stop(history, chat):
    channel, connection = chat
    ctx = await _command(history, "/stop")
    ctx.msg.metadata.update(webui=True, locale="en")
    ctx.loop._cancel_active_tasks = AsyncMock()
    done = await cmd_stop(ctx)
    await channel.send_command_result(done)
    invalid = command_reply(ctx.msg, "/stop", line("invalid.args", command="/stop"))
    await channel.send_command_result(invalid)

    live, = _sent_ws_payloads(connection)
    replay, = history.build(ctx.key)["events"]
    assert live["text"] == replay["text"] == message_text(invalid)

    await channel.send_command_result(replace(done, metadata={**done.metadata, "webui": False}))
    assert _sent_ws_payloads(connection)[-1]["text"] == "Stopped."


def test_stored_structured_receipt_replays_the_original_text(history):
    key = "websocket:chat"
    text = "已切换到 `Fast`。"
    history.sessions.append_history(key, [HistoryFact(HistoryKind.ANSWER, {
        "text": text, "side_channel": True, "command_result": {"command": "/model", "parts": [
            line("model.switched", preset="Fast"),
        ]},
    })])
    replay, = history.build(key)["events"]
    assert replay["text"] == text and replay["side_channel"] is True


async def test_model_switch_confirms_canonical_preset_to_requester(history, chat):
    channel, connection = chat
    ctx = await _command(history, "/model fast")
    ctx.args = "fast"
    ctx.loop.set_session_model_preset = AsyncMock(return_value=MagicMock(
        model_preset="Fast", model="test-model", context_window_tokens=1000,
    ))
    ctx.loop.set_session_model_preset.return_value.generation.max_tokens = 100
    await channel.send_command_result(await cmd_model(ctx))
    reply, = _sent_ws_payloads(connection)
    assert reply["command_result"] == {"command": "/model", "switched_preset": "Fast"}


async def test_large_dream_log_delivers_and_replays_the_full_diff(history, chat):
    channel, connection = chat
    ctx = await _command(history, "/dream-log")
    git = ctx.loop.consolidator.store.git
    commit = CommitInfo("abcd1234", "dream: edit", "2026-04-04 12:00")
    git.log.return_value = [commit]
    # One UTF-8 copy fits; duplicating the diff as structured parts would not.
    count = MAX_HISTORY_FACT_BYTES // 4
    diff = "diff --git a/SOUL.md b/SOUL.md\n+" + "é" * count + "\n"
    git.show_commit_diff.return_value = commit, diff
    reply = await cmd_dream_log(ctx)
    await channel.send(reply)

    live, = _sent_ws_payloads(connection)
    replay, = history.build(ctx.key)["events"]
    for event in (live, replay):
        assert event["side_channel"] is True
        assert event["text"] == message_text(reply) and diff in event["text"]
        assert "command_result" not in event


async def test_skill_image_is_signed_in_displayed_live_and_replayed_receipt(history, chat, tmp_path, monkeypatch):
    channel, connection = chat
    ctx = await _command(history, "/skill")
    image = "![Example](diagram.png)"
    skills = ctx.loop.context.skills
    skills.list_skills.return_value = [{"name": "charts"}]
    skills.get_skill_description.return_value = image
    (history.sessions.workspace / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
    monkeypatch.setattr("nanobot.webui.media_gateway.get_media_dir", _fake_media_dir(tmp_path / "media"))
    reply = await cmd_skill(ctx)
    await channel.send(reply)

    live, = _sent_ws_payloads(connection)
    source, = history.read(ctx.key)
    assert image in source["text"]
    # A restarted gateway re-signs the stored source rather than replaying a stale URL.
    media = _basic_handler(MessageBus(), workspace_path=history.sessions.workspace).media
    replay, = history.build(ctx.key, augment_assistant_text=media.rewrite_local_markdown_images)["events"]
    assert live["text"] != replay["text"]
    for event in (live, replay):
        assert "![Example](/api/media/" in event["text"]
        assert "command_result" not in event
