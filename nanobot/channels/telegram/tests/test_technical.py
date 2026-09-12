"""No-network tests for the outbound-only operational feed."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger
from pydantic import ValidationError

pytest.importorskip("telegram")

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent, StreamDeltaEvent, TurnEndEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventContext, SessionTurnStarted, TurnCompleted
from nanobot.channels.manager import ChannelManager
from nanobot.channels.telegram import technical as technical_module
from nanobot.channels.telegram.runtime import TelegramChannel, TelegramConfig
from nanobot.channels.telegram.technical import QUEUE_LIMIT, TelegramTechnicalNotifier
from nanobot.channels.telegram.technical_config import TelegramTechnicalConfig
from nanobot.events import ContextCompactionEvent, RecoveryStateEvent, RetryStatusEvent

TOKEN = "123:test-token"
TARGET = "-100123456"


@pytest.fixture(autouse=True)
def no_secret_logs():
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)))
    try:
        yield
    finally:
        logger.remove(sink)
        assert "TOP_SECRET" not in "".join(messages)


def channel(bus=None, **technical):
    return TelegramChannel(TelegramConfig(
        token=TOKEN, allow_from=["*"],
        technical={"enabled": True, "chatId": TARGET, **technical},
    ), bus or MessageBus())


def tool_message(channel_name="telegram", chat_id="7", **payload):
    return OutboundMessage(
        channel=channel_name, chat_id=chat_id, content='exec("TOP_SECRET")',
        event=ProgressEvent(content='exec("TOP_SECRET")', tool_hint=True, tool_events=[{
            "name": "exec", "phase": "start", "call_id": "SECRET_ID",
            "arguments": {"password": "TOP_SECRET"}, "result": "TOP_SECRET",
            "error": "TOP_SECRET", "files": ["/TOP_SECRET"], **payload,
        }]),
        metadata={"session_key": "TOP_SECRET", "reasoning": "TOP_SECRET"},
    )


def fake_bot():
    return SimpleNamespace(
        initialize=AsyncMock(), shutdown=AsyncMock(), send_message=AsyncMock(),
    )


@pytest.mark.parametrize("technical,token,match", [
    ({"enabled": True}, TOKEN, "chatId"),
    ({"enabled": True, "chatId": "@technical"}, TOKEN, "numeric"),
    ({"enabled": True, "chatId": "-001"}, TOKEN, "numeric"),
    ({"enabled": True, "chatId": TARGET}, "", "require"),
    ({"enabled": True, "chatId": "7"}, TOKEN, "separate"),
    ({"enabled": True, "chatId": "7", "token": "123:rotated"}, TOKEN, "separate"),
    ({"enabled": False, "includeArguments": True}, TOKEN, "Extra inputs"),
])
def test_config_rejects_unsafe_or_missing_target(technical, token, match):
    with pytest.raises(ValidationError, match=match):
        TelegramConfig(token=token, technical=technical)


def test_default_and_separate_bot_config():
    assert TelegramConfig().technical.model_dump(by_alias=True) == {
        "enabled": False, "chatId": "", "token": "",
        "profileName": "Powiadomienia", "sharedInbox": False, "mainChatId": "",
        "includeToolEvents": True, "includeStatusEvents": True,
    }
    cfg = TelegramConfig(token=TOKEN, technical={
        "enabled": True, "chatId": "7", "token": "456:private-secret",
    })
    assert not cfg.technical.uses_main_bot(TOKEN)
    assert "private-secret" not in repr(cfg.technical)


async def test_disabled_does_not_subscribe_queue_or_create_client(monkeypatch):
    bus = MessageBus()
    notifier = TelegramTechnicalNotifier(
        TelegramTechnicalConfig(), bus, main_token="", proxy=None,
    )
    monkeypatch.setattr(notifier, "_build_bot", lambda: pytest.fail("must not connect"))
    notifier.start()
    notifier.observe_outbound(tool_message())
    await bus.publish(SessionTurnStarted(RuntimeEventContext("telegram", "7", "main")))
    assert notifier._task is None and not bus._handlers and notifier._queue.empty()
    await notifier.stop()


def test_projection_redacts_all_but_names_and_closed_statuses():
    ch = channel()
    notifier = ch._technical
    notifier._active = True
    notifier.observe_outbound(tool_message())
    notifier.observe_outbound(tool_message(phase="end"))
    notifier.observe_outbound(tool_message(phase="error"))
    notifier.observe_outbound(tool_message(name="exec(TOP_SECRET)"))
    notifier.observe_outbound(tool_message(name="x" * 10000))
    notifier.observe_outbound(tool_message(phase="TOP_SECRET"))
    for event in (
        ProgressEvent(content="TOP_SECRET", reasoning=True),
        StreamDeltaEvent(content="TOP_SECRET"),
        TurnEndEvent(failure_message="TOP_SECRET"),
        ContextCompactionEvent("TOP_SECRET", "failed"),
        RetryStatusEvent("waiting", 1, None, "TOP_SECRET"),
        RecoveryStateEvent("TOP_SECRET", "TOP_SECRET", reason="TOP_SECRET"),
    ):
        notifier.observe_outbound(OutboundMessage("websocket", "main", "TOP_SECRET", event=event))
    notifier._observe_runtime(TurnCompleted(
        RuntimeEventContext("telegram", "7", "TOP_SECRET"),
        outcome="TOP_SECRET", failure_error_kind="TOP_SECRET",
    ))
    texts = list(notifier._queue._queue)
    assert texts == [
        "Tool exec: start", "Tool exec: end", "Tool exec: error",
        "Tool tool: start", "Tool tool: start", "Context: failed",
        "Request: waiting", "Recovery: updated", "Turn: updated",
    ]
    assert all(len(text) < 100 and "TOP_SECRET" not in text for text in texts)


def test_include_flags_and_bounded_queue():
    notifier = channel(includeToolEvents=False, includeStatusEvents=False)._technical
    notifier._active = True
    notifier.observe_outbound(tool_message())
    notifier._observe_runtime(SessionTurnStarted(RuntimeEventContext("telegram", "7", "main")))
    assert notifier._queue.empty()
    notifier = channel()._technical
    notifier._active = True
    for _ in range(QUEUE_LIMIT + 10):
        notifier.observe_outbound(tool_message())
    assert notifier._queue.qsize() == QUEUE_LIMIT
    assert notifier.dropped == 10
    notifier = channel()._technical
    notifier._active = True
    notifier.observe_outbound(OutboundMessage("telegram", "7", "", event=ProgressEvent(
        tool_events=[{"name": "exec", "phase": "start"}] * 1000,
    )))
    assert notifier._queue.qsize() == technical_module.MAX_TOOL_EVENTS
    assert notifier.dropped == 1000 - technical_module.MAX_TOOL_EVENTS


@pytest.mark.parametrize("method", [
    "_on_start", "_on_help", "_on_message", "_process_message_update",
    "_forward_command", "_process_forward_command", "_on_callback_query",
])
async def test_technical_ingress_ignored_before_pairing_media_or_commands(method):
    ch = channel()
    message = SimpleNamespace(chat_id=int(TARGET), chat=SimpleNamespace(id=int(TARGET)))
    update = SimpleNamespace(
        message=message, effective_user=SimpleNamespace(id=7),
        callback_query=SimpleNamespace(message=message),
    )
    ch._handle_message = AsyncMock()
    ch.is_allowed = lambda _: pytest.fail("must not reach authorization/pairing")
    await getattr(ch, method)(update, None)
    ch._handle_message.assert_not_awaited()
    assert not ch._inbound_buffers and not ch._typing_tasks


async def test_boundary_isolation_normal_chat_preserved_and_no_recursive_mirroring():
    ch = channel()
    await ch._handle_message("7", TARGET, "/restart", is_dm=True)
    assert ch.bus.inbound.empty()
    await ch._handle_message("7", "7", "hello")
    assert (await ch.bus.consume_inbound()).content == "hello"
    ch._technical._active = True
    ch.observe_outbound(tool_message(chat_id=TARGET))
    ch._technical._observe_runtime(SessionTurnStarted(RuntimeEventContext("telegram", TARGET, "main")))
    assert ch._technical._queue.empty()
    ch._wait_for_app = AsyncMock(side_effect=AssertionError("no ordinary send to technical target"))
    await ch.send(OutboundMessage("telegram", TARGET, "TOP_SECRET"))
    await ch.send_delta(TARGET, "TOP_SECRET")
    assert ch.bus.outbound.empty()


async def test_separate_bot_dm_does_not_block_main_dm_with_same_user_id():
    ch = channel(chatId="7", token="456:separate-token")
    await ch._handle_message("7", "7", "hello")
    assert ch.bus.inbound.qsize() == 1
    assert ch.accepts_outbound(OutboundMessage("telegram", "7", "answer"))
    ch._technical._active = True
    ch.observe_outbound(tool_message(chat_id="7"))
    assert ch._technical._queue.get_nowait() == "Tool exec: start"


async def test_worker_failure_is_lossy_rate_limited_and_never_publishes(monkeypatch):
    ch = channel()
    notifier = ch._technical
    bot = fake_bot()
    bot.send_message.side_effect = [RuntimeError("TOKEN TOP_SECRET"), None]
    monkeypatch.setattr(notifier, "_build_bot", lambda: bot)
    monkeypatch.setattr(technical_module, "MIN_SEND_INTERVAL", 0.01)
    monkeypatch.setattr(technical_module, "FAILURE_COOLDOWN", 0.01)
    notifier.start()
    notifier.observe_outbound(tool_message())
    notifier.observe_outbound(tool_message(phase="end"))
    await asyncio.wait_for(notifier._queue.join(), 1)
    assert notifier.failed == notifier.sent == 1
    assert bot.send_message.await_count == 2  # No retry/requeue of failed item.
    for call in bot.send_message.await_args_list:
        assert call.kwargs["chat_id"] == int(TARGET)
        assert call.kwargs["disable_notification"] is True
        assert "TOP_SECRET" not in call.kwargs["text"]
    assert ch.bus.inbound.empty() and ch.bus.outbound.empty()
    await notifier.stop()
    assert not ch.bus._handlers and notifier._queue.empty()
    bot.shutdown.assert_awaited_once()


async def test_initialization_failure_disables_feed_without_raising(monkeypatch):
    notifier = channel()._technical
    bot = fake_bot()
    bot.initialize.side_effect = RuntimeError("TOKEN TOP_SECRET")
    monkeypatch.setattr(notifier, "_build_bot", lambda: bot)
    notifier.start()
    notifier.observe_outbound(tool_message())
    await asyncio.wait_for(notifier._task, 1)
    assert notifier.failed == 1 and notifier.dropped == 1
    assert not notifier._active and not notifier._bus._handlers
    await notifier.stop()


async def test_dispatch_before_hint_filter_keeps_webui_and_final_answers(monkeypatch):
    from nanobot.config.schema import Config

    bus = MessageBus()
    ch = channel(bus)
    ch.send_tool_hints = False
    ch.send = AsyncMock()
    # Reuse a disabled Telegram adapter as a transport-neutral capture channel.
    webui = TelegramChannel(TelegramConfig(), bus)
    webui.name = "websocket"
    webui.send = AsyncMock()
    monkeypatch.setattr(ChannelManager, "_init_channels", lambda self: None)
    manager = ChannelManager(Config(), bus)
    manager.channels = {"telegram": ch, "websocket": webui}
    bot = fake_bot()
    blocked = asyncio.Event()
    # A truly stalled network coroutine must not hold channel dispatch slots.
    async def stalled_send(**_):
        await blocked.wait()
    bot.send_message.side_effect = stalled_send
    monkeypatch.setattr(ch._technical, "_build_bot", lambda: bot)
    ch._technical.start()
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())
    try:
        await bus.publish_outbound(tool_message())
        rich_event = tool_message(channel_name="websocket")
        await bus.publish_outbound(rich_event)
        final = OutboundMessage("telegram", "7", "answer")
        await bus.publish_outbound(final)
        for _ in range(100):
            if ch.send.await_count and webui.send.await_count:
                break
            await asyncio.sleep(0.005)
        ch.send.assert_awaited_once_with(final)
        webui.send.assert_awaited_once_with(rich_event)
        assert bot.send_message.await_count == 1
        assert ch._technical._queue.qsize() == 1
        assert bus.inbound.empty()
    finally:
        await manager.stop_all()
    assert not ch._technical._active


async def test_separate_bot_group_is_reserved_on_main_bot_too():
    ch = channel(token="456:separate-token")
    await ch._handle_message("7", TARGET, "do not process")
    assert ch.bus.inbound.empty()
    assert not ch.accepts_outbound(OutboundMessage("telegram", TARGET, "do not deliver"))


@pytest.mark.parametrize("separate", [False, True])
def test_technical_sdk_uses_isolated_pools_and_existing_proxy(monkeypatch, separate):
    requests = []
    clients = []
    def request(**kwargs):
        result = SimpleNamespace(**kwargs)
        requests.append(result)
        return result
    def bot(**kwargs):
        clients.append(kwargs)
        return SimpleNamespace(**kwargs)
    monkeypatch.setattr(technical_module, "HTTPXRequest", request)
    monkeypatch.setattr(technical_module, "Bot", bot)
    config = TelegramTechnicalConfig(
        enabled=True, chat_id=TARGET, token="456:separate" if separate else "",
    )
    notifier = TelegramTechnicalNotifier(
        config, MessageBus(), main_token=TOKEN, proxy="socks5://proxy.example:1080",
    )
    notifier._build_bot()
    assert clients[0]["token"] == ("456:separate" if separate else TOKEN)
    assert len(requests) == 2 and requests[0] is not requests[1]
    assert all(item.connection_pool_size == 1 for item in requests)
    assert all(item.proxy == "socks5://proxy.example:1080" for item in requests)


async def test_status_subscription_is_nonblocking_and_rate_controlled(monkeypatch):
    notifier = channel()._technical
    bot = fake_bot()
    send_times = []
    async def record(**_):
        send_times.append(asyncio.get_running_loop().time())
    bot.send_message.side_effect = record
    monkeypatch.setattr(notifier, "_build_bot", lambda: bot)
    monkeypatch.setattr(technical_module, "MIN_SEND_INTERVAL", 0.02)
    notifier.start()
    context = RuntimeEventContext("websocket", "private-chat", "private-session")
    await asyncio.wait_for(notifier._bus.publish(SessionTurnStarted(context)), 0.1)
    await asyncio.wait_for(notifier._bus.publish(TurnCompleted(context)), 0.1)
    await asyncio.wait_for(notifier._queue.join(), 1)
    assert [call.kwargs["text"] for call in bot.send_message.await_args_list] == [
        "Turn: started", "Turn: completed",
    ]
    assert send_times[1] - send_times[0] >= 0.015
    await notifier.stop()


def test_shared_notification_source_is_owner_only():
    notifier = TelegramChannel(TelegramConfig(token=TOKEN, allow_from=["7"], technical={
        "enabled": True, "chatId": TARGET, "mainChatId": "7", "sharedInbox": True,
    }), MessageBus())._technical
    notifier._active = True
    for route, chat_id in (("telegram", "8"), ("telegram", TARGET), ("websocket", "other"), ("discord", "7")):
        notifier.observe_outbound(tool_message(route, chat_id))
        notifier._observe_runtime(SessionTurnStarted(RuntimeEventContext(route, chat_id, "anything")))
    assert notifier._queue.empty()
    notifier.observe_outbound(tool_message("telegram", "7"))
    notifier.observe_outbound(tool_message("websocket", "shared-main"))
    assert list(notifier._queue._queue) == ["Tool exec: start", "Tool exec: start"]


async def test_delivery_receipt_callback_only_runs_after_confirmed_send(monkeypatch):
    notifier = channel()._technical
    bot = fake_bot()
    bot.send_message.return_value = SimpleNamespace(message_id=91)
    monkeypatch.setattr(notifier, "_build_bot", lambda: bot)
    notifier.on_delivered = AsyncMock()
    notifier.start()
    notifier.observe_outbound(tool_message())
    await asyncio.wait_for(notifier._queue.join(), 1)
    notifier.on_delivered.assert_awaited_once_with("Tool exec: start", 91)
    await notifier.stop()

    failed = channel()._technical
    bot.send_message.side_effect = RuntimeError("TOP_SECRET")
    monkeypatch.setattr(failed, "_build_bot", lambda: bot)
    failed.on_delivered = AsyncMock()
    failed.start()
    failed.observe_outbound(tool_message())
    await asyncio.wait_for(failed._queue.join(), 1)
    failed.on_delivered.assert_not_awaited()
    assert failed.failed == 1 and failed.sent == 0
    await failed.stop()


async def test_failed_receipt_storage_never_resends_delivered_notification(monkeypatch):
    notifier = channel()._technical
    bot = fake_bot()
    bot.send_message.return_value = SimpleNamespace(message_id=92)
    monkeypatch.setattr(notifier, "_build_bot", lambda: bot)
    notifier.on_delivered = AsyncMock(side_effect=OSError("TOP_SECRET"))
    notifier.start()
    notifier.observe_outbound(tool_message())
    await asyncio.wait_for(notifier._queue.join(), 1)
    assert notifier.sent == 1 and notifier.failed == 0
    bot.send_message.assert_awaited_once()
    await notifier.stop()
