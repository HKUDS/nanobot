"""Tests for the Telegram channel's whitespace-guard in the send() method.

Verifies that:
  - Whitespace-only msg.content does not trigger any Telegram API calls.
  - Whitespace-only chunks produced by _split_message are silently skipped.
  - Normal non-empty content still results in the expected API calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig


def _make_channel() -> TelegramChannel:
    config = TelegramConfig(enabled=True, token="fake-token")
    bus = MessageBus()
    channel = TelegramChannel(config=config, bus=bus)

    # Inject a fully-mocked Application so send() can run without a real bot.
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    return channel


@pytest.mark.asyncio
async def test_whitespace_only_content_does_not_call_send_message() -> None:
    """A message whose content is only whitespace must never hit the Telegram API."""
    channel = _make_channel()

    for whitespace in ["   ", "\t", "\n", "\r\n", "  \n  "]:
        channel._app.bot.send_message.reset_mock()
        msg = OutboundMessage(channel="telegram", chat_id="123456", content=whitespace)
        await channel.send(msg)
        channel._app.bot.send_message.assert_not_called(), (
            f"send_message should NOT be called for whitespace-only content {whitespace!r}"
        )


@pytest.mark.asyncio
async def test_empty_message_sentinel_does_not_call_send_message() -> None:
    """The '[empty message]' sentinel value must never trigger a Telegram API call."""
    channel = _make_channel()
    msg = OutboundMessage(channel="telegram", chat_id="123456", content="[empty message]")
    await channel.send(msg)
    channel._app.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_empty_string_does_not_call_send_message() -> None:
    """Empty string content must not trigger a Telegram API call."""
    channel = _make_channel()
    msg = OutboundMessage(channel="telegram", chat_id="123456", content="")
    await channel.send(msg)
    channel._app.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_normal_content_does_call_send_message() -> None:
    """A message with real text content must result in exactly one send_message call."""
    channel = _make_channel()
    msg = OutboundMessage(channel="telegram", chat_id="123456", content="Hello, world!")
    await channel.send(msg)
    channel._app.bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_whitespace_chunk_skipped_within_multi_chunk_message() -> None:
    """Individual whitespace-only chunks inside a larger message must be silently skipped."""
    from unittest.mock import patch

    channel = _make_channel()

    # Patch _split_message to inject a whitespace chunk between real ones.
    with patch("nanobot.channels.telegram._split_message", return_value=["Hello", "   ", "World"]):
        msg = OutboundMessage(channel="telegram", chat_id="123456", content="Hello   World")
        await channel.send(msg)

    # Only 2 real chunks ("Hello" and "World") should generate API calls; the "   " is skipped.
    assert channel._app.bot.send_message.call_count == 2, (
        "Expected exactly 2 send_message calls (whitespace chunk must be skipped)."
    )
