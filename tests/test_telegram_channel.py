"""Tests for nanobot.channels.telegram — polling and webhook modes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs) -> TelegramConfig:
    defaults = dict(enabled=True, token="test-token-123", allow_from=["*"])
    defaults.update(kwargs)
    return TelegramConfig(**defaults)


def _make_fake_app(monkeypatch) -> tuple[MagicMock, MagicMock]:
    """Patch Application.builder() and return (mock_app, mock_updater)."""
    mock_updater = MagicMock()
    mock_updater.start_polling = AsyncMock()
    mock_updater.start_webhook = AsyncMock()
    mock_updater.stop = AsyncMock()

    mock_bot = AsyncMock()
    mock_bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
    mock_bot.set_my_commands = AsyncMock()

    mock_app = MagicMock()
    mock_app.bot = mock_bot
    mock_app.updater = mock_updater
    mock_app.initialize = AsyncMock()
    mock_app.start = AsyncMock()
    mock_app.stop = AsyncMock()
    mock_app.shutdown = AsyncMock()
    mock_app.add_handler = MagicMock()
    mock_app.add_error_handler = MagicMock()

    mock_builder = MagicMock()
    mock_builder.token.return_value = mock_builder
    mock_builder.request.return_value = mock_builder
    mock_builder.get_updates_request.return_value = mock_builder
    mock_builder.proxy.return_value = mock_builder
    mock_builder.get_updates_proxy.return_value = mock_builder
    mock_builder.build.return_value = mock_app

    monkeypatch.setattr(
        "nanobot.channels.telegram.Application.builder",
        MagicMock(return_value=mock_builder),
    )
    return mock_app, mock_updater


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_polling_mode_calls_start_polling(monkeypatch) -> None:
    """With mode='polling', start() must call updater.start_polling()."""
    cfg = _make_config(mode="polling")
    mock_app, mock_updater = _make_fake_app(monkeypatch)

    channel = TelegramChannel(cfg, MessageBus())
    # Drive start() until the first asyncio.sleep to avoid running forever
    channel._running = True

    async def _stop_after_start():
        await asyncio.sleep(0.05)
        channel._running = False

    await asyncio.gather(channel.start(), _stop_after_start())

    mock_updater.start_polling.assert_awaited_once()
    mock_updater.start_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_mode_calls_start_webhook(monkeypatch) -> None:
    """With mode='webhook', start() must call updater.start_webhook() with config values."""
    cfg = _make_config(
        mode="webhook",
        webhook_url="https://bot.example.com/webhook/telegram",
        webhook_listen="127.0.0.1",
        webhook_port=8080,
        webhook_path="/webhook/telegram",
    )
    mock_app, mock_updater = _make_fake_app(monkeypatch)

    channel = TelegramChannel(cfg, MessageBus())
    channel._running = True

    async def _stop_after_start():
        await asyncio.sleep(0.05)
        channel._running = False

    await asyncio.gather(channel.start(), _stop_after_start())

    mock_updater.start_polling.assert_not_awaited()
    mock_updater.start_webhook.assert_awaited_once_with(
        listen="127.0.0.1",
        port=8080,
        url_path="/webhook/telegram",
        webhook_url="https://bot.example.com/webhook/telegram",
        drop_pending_updates=True,
        allowed_updates=["message"],
    )


@pytest.mark.asyncio
async def test_webhook_mode_raises_when_url_empty(monkeypatch) -> None:
    """mode='webhook' with an empty webhook_url must raise ValueError immediately."""
    cfg = _make_config(mode="webhook", webhook_url="")
    _make_fake_app(monkeypatch)

    channel = TelegramChannel(cfg, MessageBus())

    with pytest.raises(ValueError, match="webhookUrl"):
        await channel.start()
