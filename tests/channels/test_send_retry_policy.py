import asyncio
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("telegram")
from telegram.error import NetworkError, RetryAfter, TimedOut

from nanobot.bus.delivery import ChannelNotReadyError
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels import manager as manager_module
from nanobot.channels.manager import ChannelManager
from nanobot.channels.telegram import runtime as telegram_module
from nanobot.channels.telegram.runtime import (
    TELEGRAM_MAX_MESSAGE_LEN,
    TelegramChannel,
    _split_telegram_markdown,
)
from nanobot.config.schema import Config


def make_manager(tmp_path):
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    return ChannelManager(config, MessageBus(), config_path=tmp_path / "config.json")


def telegram_channel(manager):
    channel = TelegramChannel({"token": "test", "rich_messages": False}, manager.bus)
    channel._app = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    channel._app_ready.set()
    return channel


async def test_telegram_exhausted_second_chunk_never_replays_successful_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(manager_module, "_SEND_RETRY_DELAYS", (0,))
    monkeypatch.setattr(telegram_module, "_SEND_RETRY_BASE_DELAY", 0)
    manager = make_manager(tmp_path)
    channel = telegram_channel(manager)
    text = "a" * TELEGRAM_MAX_MESSAGE_LEN + "\n" + "b" * 20
    chunks = _split_telegram_markdown(text, TELEGRAM_MAX_MESSAGE_LEN)
    assert len(chunks) == 2
    submitted = []

    async def send_message(**kwargs):
        submitted.append(kwargs["text"])
        if kwargs["text"] != chunks[0]:
            raise TimedOut("second part exhausted")
        return SimpleNamespace(message_id=1)

    channel._app.bot.send_message.side_effect = send_message
    await manager._send_with_retry(channel, OutboundMessage("telegram", "1", text))
    assert submitted == [chunks[0], chunks[1], chunks[1], chunks[1]]


@pytest.mark.parametrize(("error", "requests"), [
    (TimedOut("timeout"), 3),
    (RetryAfter(0), 3),
    (NetworkError("ambiguous transport error"), 1),
    (RuntimeError("unknown send result"), 1),
])
async def test_telegram_manager_does_not_multiply_part_retry_budget(tmp_path, monkeypatch, error, requests):
    monkeypatch.setattr(manager_module, "_SEND_RETRY_DELAYS", (0,))
    monkeypatch.setattr(telegram_module, "_SEND_RETRY_BASE_DELAY", 0)
    manager = make_manager(tmp_path)
    channel = telegram_channel(manager)
    channel._app.bot.send_message.side_effect = error
    await manager._send_with_retry(channel, OutboundMessage("telegram", "1", "result"))
    assert channel._app.bot.send_message.await_count == requests


async def test_telegram_manager_retries_only_pre_submit_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(manager_module, "_SEND_RETRY_DELAYS", (0,))
    manager = make_manager(tmp_path)
    channel = telegram_channel(manager)
    channel._wait_for_app = AsyncMock(side_effect=[None, channel._app])
    await manager._send_with_retry(channel, OutboundMessage("telegram", "1", "result"))
    assert channel._wait_for_app.await_count == 2
    channel._app.bot.send_message.assert_awaited_once()


async def test_manager_equal_jitter_uses_capped_retry_delays(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    manager.config.channels.send_max_retries = 6
    channel = SimpleNamespace(send=AsyncMock(side_effect=OSError("offline")),
                              should_retry_send_error=Mock(return_value=True))
    uniform = Mock(side_effect=lambda lower, upper: (lower + upper) / 2)
    monkeypatch.setattr(random, "uniform", uniform)
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    await manager._send_with_retry(channel, OutboundMessage("test", "1", "result"))
    assert [call.args for call in uniform.call_args_list] == [(0.5, 1), (1.0, 2), (2.0, 4), (2.0, 4), (2.0, 4)]
    assert [call.args[0] for call in sleep.await_args_list] == [0.75, 1.5, 3, 3, 3]


async def test_manager_deadline_clamps_jitter_and_keeps_pre_submit_retry(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    manager.config.channels.send_max_retries = 1
    channel = SimpleNamespace(send=AsyncMock(side_effect=[ChannelNotReadyError("starting"), None]),
                              should_retry_send_error=Mock(return_value=True))
    monkeypatch.setattr(manager_module, "_SEND_RETRY_DELAYS", (4,))
    monkeypatch.setattr(random, "uniform", lambda lower, upper: upper)
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    await manager._send_with_retry(channel, OutboundMessage("test", "1", "result"),
                                   deadline=asyncio.get_running_loop().time() + 2)
    assert channel.send.await_count == 2
    assert 0 < sleep.await_args.args[0] <= 2


async def test_telegram_restart_notice_deadline_never_replays_unknown_result(tmp_path):
    from nanobot.utils.restart import RestartNotice

    manager = make_manager(tmp_path)
    channel = telegram_channel(manager)
    channel._running = True
    channel._app.bot.send_message.side_effect = NetworkError("unknown delivery")
    manager.channels["telegram"] = channel
    await manager._send_restart_notice_when_started(
        RestartNotice(channel="telegram", chat_id="1", started_at_raw=""), timeout_s=0.1,
    )
    channel._app.bot.send_message.assert_awaited_once()
