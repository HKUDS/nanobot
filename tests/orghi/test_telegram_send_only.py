"""Tests for TelegramChannel send_only behavior (orghi custom feature)."""

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig


@dataclass
class _MockAppTracker:
    add_handler_calls: list = field(default_factory=list)
    start_polling_called: list = field(default_factory=list)
    updater_stop_called: list = field(default_factory=list)


def _make_mock_app(tracker: _MockAppTracker) -> MagicMock:
    mock_app = MagicMock()
    mock_app.add_handler = MagicMock()
    mock_app.add_error_handler = MagicMock()
    mock_app.initialize = AsyncMock()
    mock_app.start = AsyncMock()
    mock_app.stop = AsyncMock()
    mock_app.shutdown = AsyncMock()

    mock_bot = MagicMock()
    mock_bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
    mock_bot.set_my_commands = AsyncMock()
    mock_app.bot = mock_bot

    async def track_start_polling(**kw: object) -> None:
        tracker.start_polling_called.append(True)

    async def track_updater_stop() -> None:
        tracker.updater_stop_called.append(True)

    mock_updater = MagicMock()
    mock_updater.start_polling = AsyncMock(side_effect=track_start_polling)
    mock_updater.stop = AsyncMock(side_effect=track_updater_stop)
    mock_app.updater = mock_updater

    def track_add_handler(handler: object) -> None:
        tracker.add_handler_calls.append(("add_handler", handler))

    mock_app.add_handler.side_effect = track_add_handler
    return mock_app


def _make_mock_builder(mock_app: MagicMock) -> MagicMock:
    mock_builder = MagicMock()
    mock_builder.token.return_value = mock_builder
    mock_builder.request.return_value = mock_builder
    mock_builder.get_updates_request.return_value = mock_builder
    mock_builder.build.return_value = mock_app
    return mock_builder


@pytest.fixture
def telegram_config() -> TelegramConfig:
    return TelegramConfig(token="fake-token-for-testing", enabled=True)


@pytest.fixture
def mock_telegram_env() -> tuple[MagicMock, MagicMock, _MockAppTracker]:
    tracker = _MockAppTracker()
    mock_app = _make_mock_app(tracker)
    mock_builder = _make_mock_builder(mock_app)
    return mock_app, mock_builder, tracker


@pytest.mark.asyncio
async def test_start_send_only_sets_flag(
    bus: MessageBus,
    telegram_config: TelegramConfig,
    mock_telegram_env: tuple[MagicMock, MagicMock, _MockAppTracker],
) -> None:
    _, mock_builder, _ = mock_telegram_env
    channel = TelegramChannel(telegram_config, bus)

    with patch("nanobot.channels.telegram.Application") as MockApp:  # noqa: N806
        MockApp.builder.return_value = mock_builder
        await channel.start(send_only=True)

    assert channel._send_only is True


@pytest.mark.asyncio
async def test_start_send_only_skips_handlers_and_polling(
    bus: MessageBus,
    telegram_config: TelegramConfig,
    mock_telegram_env: tuple[MagicMock, MagicMock, _MockAppTracker],
) -> None:
    mock_app, mock_builder, tracker = mock_telegram_env
    channel = TelegramChannel(telegram_config, bus)

    with patch("nanobot.channels.telegram.Application") as MockApp:  # noqa: N806
        MockApp.builder.return_value = mock_builder
        await channel.start(send_only=True)

    handler_calls = [
        c for c in tracker.add_handler_calls if c[0] == "add_handler"
    ]
    assert len(handler_calls) == 0
    assert len(tracker.start_polling_called) == 0


@pytest.mark.asyncio
async def test_start_normal_adds_handlers_and_polls(
    bus: MessageBus,
    telegram_config: TelegramConfig,
    mock_telegram_env: tuple[MagicMock, MagicMock, _MockAppTracker],
) -> None:
    mock_app, mock_builder, tracker = mock_telegram_env
    channel = TelegramChannel(telegram_config, bus)

    with patch("nanobot.channels.telegram.Application") as MockApp:  # noqa: N806
        MockApp.builder.return_value = mock_builder
        start_task = asyncio.create_task(channel.start(send_only=False))
        await asyncio.sleep(0.1)
        channel._running = False
        await start_task

    handler_calls = [
        c for c in tracker.add_handler_calls if c[0] == "add_handler"
    ]
    assert len(handler_calls) == 4
    assert len(tracker.start_polling_called) == 1


@pytest.mark.asyncio
async def test_stop_send_only_skips_updater_stop(
    bus: MessageBus,
    telegram_config: TelegramConfig,
    mock_telegram_env: tuple[MagicMock, MagicMock, _MockAppTracker],
) -> None:
    mock_app, mock_builder, tracker = mock_telegram_env
    channel = TelegramChannel(telegram_config, bus)

    with patch("nanobot.channels.telegram.Application") as MockApp:  # noqa: N806
        MockApp.builder.return_value = mock_builder
        await channel.start(send_only=True)
        await channel.stop()

    assert len(tracker.updater_stop_called) == 0


@pytest.mark.asyncio
async def test_stop_normal_calls_updater_stop(
    bus: MessageBus,
    telegram_config: TelegramConfig,
    mock_telegram_env: tuple[MagicMock, MagicMock, _MockAppTracker],
) -> None:
    mock_app, mock_builder, tracker = mock_telegram_env
    channel = TelegramChannel(telegram_config, bus)

    with patch("nanobot.channels.telegram.Application") as MockApp:  # noqa: N806
        MockApp.builder.return_value = mock_builder
        start_task = asyncio.create_task(channel.start(send_only=False))
        await asyncio.sleep(0.1)
        await channel.stop()
        await start_task

    assert len(tracker.updater_stop_called) == 1
