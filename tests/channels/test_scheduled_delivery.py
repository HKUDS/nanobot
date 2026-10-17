"""Exercise scheduled delivery through the real gateway pipeline, without external sends."""

import asyncio
import json
import os
import sqlite3
from functools import partial
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.delivery import (
    DELIVERY_RUN_META,
    ChannelNotReadyError,
    DeliveryRejectedError,
    DeliveryRequest,
)
from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels import outbox as outbox_module
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.channels.outbox import DeliveryOutbox
from nanobot.channels.registry import load_channel_plugin
from nanobot.channels.whatsapp.runtime import WhatsAppChannel
from nanobot.config.schema import Config
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager


def rows(outbox):
    with sqlite3.connect(outbox.path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM deliveries ORDER BY created")]


def make_manager(tmp_path, sessions=None):
    config = Config.model_validate({"channels": {
        "websocket": {"enabled": False}, "sendProgress": False, "sendToolHints": False,
    }})
    bus = MessageBus()
    manager = ChannelManager(config, bus, config_path=tmp_path / "config.json", session_manager=sessions)
    return manager


def message(channel="whatsapp", content="result", generation=None):
    return OutboundMessage(channel, "synthetic", content,
                           delivery=DeliveryRequest("run-1", "whatsapp:synthetic", generation))


async def drain(manager):
    async with asyncio.timeout(5):
        while manager.bus.outbound_size or manager._outbound_tasks:
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("legacy_message,one_shot,origin", [
    (False, False, "whatsapp"), (True, False, "whatsapp"), (True, True, "whatsapp"),
    (True, False, "websocket"),
])
async def test_cron_offline_restart_and_reconnect_do_not_rerun_model(tmp_path, monkeypatch, legacy_message, one_shot, origin):
    monkeypatch.setattr(outbox_module, "RETRY_SECONDS", 0)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    manager = make_manager(tmp_path, sessions)
    bus = manager.bus
    cron = CronService(tmp_path / "cron" / "jobs.json")
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "offline-test-model"
    provider.generation = GenerationSettings(max_tokens=100)
    provider.can_resume_conversation_state.return_value = False
    provider.estimate_prompt_tokens.return_value = (100, "test")
    calls = []

    async def reply(**kwargs):
        calls.append(kwargs)
        if legacy_message and len(calls) == 1:
            arguments = {"content": "Diagnostic result"}
            if origin == "websocket":
                arguments.update(channel="whatsapp", chat_id="synthetic")
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="send", name="message", arguments=arguments,
            )], finish_reason="tool_calls")
        return LLMResponse(content="Diagnostic result")

    provider.chat_stream_with_retry = reply
    agent = AgentLoop(bus=bus, provider=provider, workspace=workspace,
                      model="offline-test-model", session_manager=sessions,
                      tools_config=manager.config.tools, cron_service=cron)
    cron.on_job = partial(run_bound_cron_job, agent=agent, cron=cron)
    channel = WhatsAppChannel({}, bus)
    channel.send_progress = False
    channel.send_tool_hints = False
    channel._client = MagicMock(send_message=AsyncMock())
    channel._connected = False
    monkeypatch.setattr(channel, "_build_jid", lambda value: value)
    monkeypatch.setattr(channel, "stop", AsyncMock())
    manager.channels["whatsapp"] = channel
    if origin == "websocket":
        manager.channels["websocket"] = MagicMock(spec=BaseChannel, send=AsyncMock(), stop=AsyncMock())
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())
    # Legacy channel/to fields still normalize through the existing binding migration.
    schedule = CronSchedule(kind="at", at_ms=4102444800000) if one_shot else CronSchedule(kind="every", every_ms=86400000)
    if origin == "websocket":
        # A WebUI-created task remains in its source chat even when its instructions
        # explicitly request a separate send. Recovery must keep that send's target.
        with request_context(RequestContext("websocket", "source", session_key="websocket:source",
                                            metadata={"webui": True, "_wants_stream": True})):
            await CronTool(cron).execute(action="add", name="Reminder", every_seconds=86400,
                message="Use message to send Diagnostic result to whatsapp:synthetic")
        job = cron.list_jobs()[0]
        assert job.payload.session_key == "websocket:source"
        assert job.payload.origin_channel == "websocket"
    else:
        job = cron.add_job("Reminder", schedule,
                           "Use message to send Diagnostic result" if legacy_message else "Return Diagnostic result",
                           deliver=True, channel="whatsapp", to="synthetic", delete_after_run=one_shot,
                           channel_meta={"_wants_stream": True})

    def whatsapp_rows():
        return [row for row in rows(manager._outbox) if row["channel"] == "whatsapp"]

    try:
        assert await asyncio.wait_for(cron.run_job(job.id), 15)
        await drain(manager)
        if one_shot:
            assert cron.list_jobs() == []
        else:
            assert cron.list_jobs()[0].state.last_status == "ok"
        assert len(whatsapp_rows()) == 1
        assert whatsapp_rows()[0]["status"] == "pending"
        if origin == "websocket":
            saved = json.loads(whatsapp_rows()[0]["payload"])
            assert saved["delivery"]["session_key"] == "websocket:source"
            assert saved["metadata"] == {}
        channel._client.send_message.assert_not_called()
        count = len(calls)
        assert count == (2 if legacy_message else 1)
        assert DELIVERY_RUN_META not in json.dumps(calls[0]["messages"])
        assert "Diagnostic result" not in calls[0]["messages"][0]["content"]
        await manager.stop_all()
        # A second gateway uses the saved result; no timer, agent, or model is restarted.
        manager = make_manager(tmp_path, sessions)
        manager.channels["whatsapp"] = channel
        channel._connected = True
        await manager._recover_scheduled()
        await drain(manager)
        channel._client.send_message.assert_awaited_once_with("synthetic", "Diagnostic result")
        assert whatsapp_rows()[0]["status"] == "sent"
        assert whatsapp_rows()[0]["payload"] is None
        again = make_manager(tmp_path, sessions)
        again.channels["whatsapp"] = channel
        await again._recover_scheduled()
        assert channel._client.send_message.await_count == 1
        assert len(calls) == count
        # Existing jobs still load after delivery state is added beside them.
        old_jobs = CronService(cron.store_path).list_jobs()
        assert old_jobs == [] if one_shot else old_jobs[0].payload.message == job.payload.message
    finally:
        await manager.stop_all()
        cron.stop()
        await agent.aclose()


@pytest.mark.parametrize("failure", [TimeoutError("response lost"), asyncio.CancelledError()])
async def test_uncertain_attempt_is_not_replayed(tmp_path, failure):
    manager = make_manager(tmp_path)
    channel = MagicMock(spec=BaseChannel)
    channel.send = AsyncMock(side_effect=failure)
    msg = message()
    await manager.bus.publish_outbound(msg)
    if isinstance(failure, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await manager._send_scheduled(channel, msg)
    else:
        await manager._send_scheduled(channel, msg)
    assert rows(manager._outbox)[0]["status"] == "unknown"
    assert DeliveryOutbox(manager._outbox.path).ready() == []
    channel.send.assert_awaited_once()


async def test_legacy_broadcast_has_independent_targets_and_no_foreign_thread_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(outbox_module, "RETRY_SECONDS", 0)
    manager = make_manager(tmp_path)
    tool = MessageTool(send_callback=manager.bus.publish_outbound, workspace=tmp_path)
    with request_context(RequestContext(
        "telegram", "source", session_key="telegram:source", metadata={
            DELIVERY_RUN_META: "run-1", "message_thread_id": 42, "message_id": "parent",
        },
    )):
        for channel in ("slack", "whatsapp"):
            assert str(await tool.execute(content="result", channel=channel, chat_id="target")).startswith("Message queued")
    messages = [manager.bus.outbound.get_nowait() for _ in range(2)]
    assert all(msg.metadata == {} for msg in messages)
    assert len({msg.delivery_id for msg in messages}) == 2
    healthy = MagicMock(spec=BaseChannel, send=AsyncMock())
    offline = MagicMock(spec=BaseChannel, send=AsyncMock(side_effect=ChannelNotReadyError()))
    await manager._send_scheduled(healthy, messages[0])
    await manager._send_scheduled(offline, messages[1])
    assert [row["status"] for row in rows(manager._outbox)] == ["sent", "pending"]
    assert [msg.channel for msg in manager._outbox.ready()] == ["whatsapp"]


async def test_queue_acceptance_survives_restart_but_inflight_is_unknown(tmp_path):
    manager = make_manager(tmp_path)
    pending, inflight = message(), message(content="second")
    inflight.chat_id = "other-destination"
    await manager.bus.publish_outbound(pending)
    await manager.bus.publish_outbound(inflight)
    assert manager._outbox.claim(inflight)
    restarted = DeliveryOutbox(manager._outbox.path)
    assert [msg.delivery_id for msg in restarted.ready()] == [pending.delivery_id]
    assert [row["status"] for row in rows(restarted)] == ["pending", "unknown"]


async def test_queue_bounds_expiry_and_untracked_events(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    monkeypatch.setattr(outbox_module, "MAX_PENDING", 1)
    event = message()
    event.event = ProgressEvent(tool_hint=True)
    await manager.bus.publish_outbound(event)
    await manager.bus.publish_outbound(OutboundMessage("slack", "synthetic", "ordinary reply"))
    assert not manager._outbox.path.exists()
    first = message()
    await manager.bus.publish_outbound(first)
    with pytest.raises(RuntimeError, match="queue is full"):
        await manager.bus.publish_outbound(message(content="second"))
    with pytest.raises(ValueError, match="1 MiB"):
        await manager.bus.publish_outbound(message(content="a" * (1024 * 1024)))
    monkeypatch.setattr(outbox_module, "MAX_AGE_SECONDS", 0)
    assert manager._outbox.ready() == []
    assert rows(manager._outbox)[0]["error"] == "expired"
    assert not manager._outbox.claim(first)
    if os.name != "nt":
        assert manager._outbox.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("operation", ["delete", "reset"])
async def test_pending_result_cannot_send_after_source_session_is_replaced(tmp_path, operation):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    session = await sessions.state.get("whatsapp:synthetic")
    manager = make_manager(tmp_path, sessions)
    channel = MagicMock(spec=BaseChannel, send=AsyncMock())
    msg = message(generation=session.generation)
    try:
        await manager.bus.publish_outbound(msg)
        await getattr(sessions.state, operation)(session.key)
        await manager._send_scheduled(channel, msg)
        channel.send.assert_not_called()
        assert rows(manager._outbox)[0]["error"] == "session_replaced"
    finally:
        await sessions.state.aclose()


async def test_recovery_keeps_destination_order_and_does_not_block_other_chats(tmp_path, monkeypatch):
    monkeypatch.setattr(outbox_module, "RETRY_SECONDS", 0)
    manager = make_manager(tmp_path)
    first, second, other = message(content="first"), message(content="second"), message(content="other")
    other.chat_id = "another-chat"
    for msg in (first, second, other):
        await manager.bus.publish_outbound(msg)
        await manager.bus.consume_outbound()
    channel = MagicMock(spec=BaseChannel, send=AsyncMock(side_effect=ChannelNotReadyError()))
    await manager._send_scheduled(channel, first)
    channel.send.side_effect = None
    await manager._send_scheduled(channel, second)
    await manager._send_scheduled(channel, other)
    assert [call.args[0].content for call in channel.send.await_args_list] == ["first", "other"]
    manager.channels["whatsapp"] = channel
    await manager._recover_scheduled()
    await drain(manager)
    assert [call.args[0].content for call in channel.send.await_args_list] == ["first", "other", "first", "second"]
    # A stale queued copy must not downgrade the durable successful result.
    manager._outbox.finish(first, "failed", "channel_disabled")
    assert all(row["status"] == "sent" for row in rows(manager._outbox))


async def test_relocated_instance_finds_queue_and_disabled_channel_does_not_send(tmp_path):
    original = tmp_path / "original"
    manager = make_manager(original)
    await manager.bus.publish_outbound(message())
    moved = tmp_path / "moved"
    original.rename(moved)
    restarted = make_manager(moved)
    await restarted._recover_scheduled()
    assert rows(restarted._outbox)[0]["error"] == "channel_disabled"
    assert not original.exists()


async def test_recovery_rechecks_attachment_workspace_boundary(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    session = await sessions.state.get("whatsapp:synthetic")
    manager = make_manager(tmp_path, sessions)
    manager.config.agents.defaults.workspace = str(workspace)
    manager.config.tools.restrict_to_workspace = True
    attachment = workspace / "report.txt"
    attachment.write_text("report")
    msg = message(generation=session.generation)
    msg.media = [str(attachment)]
    channel = MagicMock(spec=BaseChannel, send=AsyncMock())
    try:
        await manager.bus.publish_outbound(msg)
        attachment.unlink()
        private = tmp_path / "private.txt"
        private.write_text("not authorized")
        attachment.symlink_to(private)
        await manager._send_scheduled(channel, msg)
        channel.send.assert_not_called()
        assert rows(manager._outbox)[0]["error"] == "attachment_access_denied"
    finally:
        await sessions.state.aclose()


@pytest.mark.parametrize("name", [
    "whatsapp", "telegram", "discord", "slack", "matrix", "mattermost", "feishu",
    "qq", "wecom", "weixin", "napcat", "msteams", "linear", "signal", "dingtalk",
    "mochat", "email",
])
async def test_unavailable_adapter_does_not_report_success(name, monkeypatch):
    cls = load_channel_plugin(name).load_channel_class()
    channel = cls(cls.default_config(), MessageBus())
    if name == "dingtalk":
        monkeypatch.setattr(channel, "_get_access_token", AsyncMock(return_value=None))
    with pytest.raises((ChannelNotReadyError, DeliveryRejectedError)):
        await channel.send(OutboundMessage(name, "synthetic", "result"))
