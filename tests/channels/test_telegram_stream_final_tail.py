"""An unchanged first stream chunk must not suppress the remaining chunks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram.runtime import TelegramChannel, TelegramConfig, _StreamBuf


@pytest.mark.asyncio
@pytest.mark.parametrize("edit_errors", [
    [None],
    [BadRequest("Message is not modified")],
    [BadRequest("Cannot parse entities"), BadRequest("Message is not modified")],
])
async def test_final_stream_sends_tail_when_primary_message_is_unchanged(edit_errors):
    channel = TelegramChannel(TelegramConfig(token="test"), MessageBus())
    bot = SimpleNamespace(
        edit_message_text=AsyncMock(side_effect=edit_errors),
        send_message=AsyncMock(),
    )
    channel._app = SimpleNamespace(bot=bot)
    channel._app_ready.set()
    channel._stream_bufs["123"] = _StreamBuf(
        text="a" * 4000 + "\nRemaining response", message_id=7, stream_id="stream",
    )

    await channel.send_delta(
        "123", "", {"message_thread_id": 42}, stream_id="stream", stream_end=True,
    )

    assert bot.edit_message_text.await_count == len(edit_errors)
    bot.send_message.assert_awaited_once_with(
        chat_id=123, text="Remaining response", parse_mode="HTML", message_thread_id=42,
    )
    assert "123" not in channel._stream_bufs
