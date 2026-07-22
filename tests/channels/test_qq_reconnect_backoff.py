"""Regression tests for QQ WebSocket reconnect backoff."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

pytest.importorskip("botpy")


def _make_channel():
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.qq.runtime import QQChannel, QQConfig

    bus = MessageBus()
    config = QQConfig(app_id="test_app", secret="test_secret")
    return QQChannel(config, bus)


def _make_bot(channel):
    from nanobot.channels.qq.runtime import _make_bot_class

    bot_cls = _make_bot_class(channel)
    bot = bot_cls.__new__(bot_cls)

    bot._connection = MagicMock()
    bot._connection.add = MagicMock()
    bot._ws_backoff = {}
    bot._ws_retry_at = {}
    return bot


@pytest.mark.asyncio
async def test_bot_connect_dns_error_accounts_for_sdk_pacing():
    import asyncio

    from botpy.connection import ConnectionSession

    channel = _make_channel()
    bot = _make_bot(channel)

    dns_error = aiohttp.ClientConnectorError(
        connection_key=MagicMock(),
        os_error=OSError("No address associated with hostname"),
    )

    clock = 0.0
    attempt_times = []

    async def fail_connect():
        attempt_times.append(clock)
        raise dns_error

    async def advance_clock(delay):
        nonlocal clock
        clock += delay

    connection = ConnectionSession(
        max_async=1,
        connect=bot.bot_connect,
        dispatch=MagicMock(),
        loop=asyncio.get_running_loop(),
    )
    bot._connection = connection
    session = {"session_id": "", "url": "wss://example.com/ws"}
    connection.add(session)

    with (
        patch("nanobot.channels.qq.runtime.BotWebSocket") as mock_ws_cls,
        patch("nanobot.channels.qq.runtime.time.monotonic", side_effect=lambda: clock),
        patch("asyncio.sleep", side_effect=advance_clock),
    ):
        mock_client = MagicMock()
        mock_client.ws_connect = AsyncMock(side_effect=fail_connect)
        mock_ws_cls.return_value = mock_client

        for _ in range(3):
            await connection.multi_run(session_interval=5)

        assert attempt_times == [0, 5, 15]
        assert bot._ws_backoff[id(session)] == 40
        assert connection._session_list == [session]


@pytest.mark.asyncio
async def test_bot_connect_dns_error_no_traceback(capsys):
    channel = _make_channel()
    bot = _make_bot(channel)

    dns_error = aiohttp.ClientConnectorError(
        connection_key=MagicMock(),
        os_error=OSError("No address associated with hostname"),
    )

    with (
        patch(
            "nanobot.channels.qq.runtime.BotWebSocket"
        ) as mock_ws_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_client = MagicMock()
        mock_client.ws_connect = AsyncMock(side_effect=dns_error)
        mock_ws_cls.return_value = mock_client

        session = {"session_id": "", "url": "wss://example.com/ws"}
        await bot.bot_connect(session)

    captured = capsys.readouterr()
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


@pytest.mark.asyncio
async def test_bot_connect_connector_error_applies_backoff():
    channel = _make_channel()
    bot = _make_bot(channel)

    connector_error = aiohttp.ClientConnectorError(
        connection_key=MagicMock(),
        os_error=ConnectionRefusedError("Connection refused"),
    )

    with (
        patch(
            "nanobot.channels.qq.runtime.BotWebSocket"
        ) as mock_ws_cls,
        patch("asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        mock_client = MagicMock()
        mock_client.ws_connect = AsyncMock(side_effect=connector_error)
        mock_ws_cls.return_value = mock_client

        session = {"session_id": "", "url": "wss://example.com/ws"}
        await bot.bot_connect(session)

        mock_sleep.assert_not_awaited()
        assert bot._ws_backoff[id(session)] == 10


@pytest.mark.asyncio
async def test_bot_connect_backoff_doubles_and_caps():
    from nanobot.channels.qq.runtime import _RECONNECT_BACKOFF_MAX

    channel = _make_channel()
    bot = _make_bot(channel)

    dns_error = aiohttp.ClientConnectorError(
        connection_key=MagicMock(),
        os_error=OSError("DNS failure"),
    )

    with (
        patch(
            "nanobot.channels.qq.runtime.BotWebSocket"
        ) as mock_ws_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_client = MagicMock()
        mock_client.ws_connect = AsyncMock(side_effect=dns_error)
        mock_ws_cls.return_value = mock_client

        session = {"session_id": "", "url": "wss://example.com/ws"}

        for expected_backoff in [5, 10, 20, 40, 80, 160, 300, 300]:
            bot._ws_backoff[id(session)] = expected_backoff
            bot._ws_retry_at.pop(id(session), None)
            await bot.bot_connect(session)
            expected_next = min(expected_backoff * 2, _RECONNECT_BACKOFF_MAX)
            assert bot._ws_backoff[id(session)] == expected_next


@pytest.mark.asyncio
async def test_bot_connect_success_resets_backoff():
    channel = _make_channel()
    bot = _make_bot(channel)
    session = {"session_id": "", "url": "wss://example.com/ws"}
    bot._ws_backoff[id(session)] = 80
    bot._ws_retry_at[id(session)] = 0.0

    with patch("nanobot.channels.qq.runtime.BotWebSocket") as mock_ws_cls:
        mock_client = MagicMock()
        mock_client.ws_connect = AsyncMock()
        mock_ws_cls.return_value = mock_client

        await bot.bot_connect(session)

        assert id(session) not in bot._ws_backoff
        assert id(session) not in bot._ws_retry_at
        bot._connection.add.assert_not_called()


@pytest.mark.asyncio
async def test_bot_connect_non_network_error_still_requeues():
    channel = _make_channel()
    channel.logger = MagicMock()
    bot = _make_bot(channel)

    runtime_error = RuntimeError("Unexpected error")

    with (
        patch(
            "nanobot.channels.qq.runtime.BotWebSocket"
        ) as mock_ws_cls,
        patch("asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        mock_client = MagicMock()
        mock_client.ws_connect = AsyncMock(side_effect=runtime_error)
        mock_ws_cls.return_value = mock_client

        session = {"session_id": "", "url": "wss://example.com/ws"}
        await bot.bot_connect(session)

        mock_sleep.assert_not_awaited()
        bot._connection.add.assert_called_once_with(session)
        channel.logger.exception.assert_called_once_with(
            "QQ bot WebSocket error: {}", runtime_error
        )


@pytest.mark.asyncio
async def test_bot_connect_per_session_backoff_isolated():
    channel = _make_channel()
    bot = _make_bot(channel)

    connector_error = aiohttp.ClientConnectorError(
        connection_key=MagicMock(),
        os_error=ConnectionRefusedError("Connection refused"),
    )

    with (
        patch(
            "nanobot.channels.qq.runtime.BotWebSocket"
        ) as mock_ws_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_client = MagicMock()
        mock_client.ws_connect = AsyncMock(side_effect=connector_error)
        mock_ws_cls.return_value = mock_client

        session_a = {"session_id": "a", "url": "wss://example.com/ws"}
        session_b = {"session_id": "b", "url": "wss://example.com/ws"}

        await bot.bot_connect(session_a)
        assert bot._ws_backoff[id(session_a)] == 10

        await bot.bot_connect(session_b)
        assert bot._ws_backoff[id(session_b)] == 10

        await bot.bot_connect(session_a)
        assert bot._ws_backoff[id(session_a)] == 20

        assert bot._ws_backoff[id(session_b)] == 10

def test_is_network_error_classification():
    from nanobot.channels.qq.runtime import _is_network_error

    assert _is_network_error(
        aiohttp.ClientConnectorError(
            connection_key=MagicMock(),
            os_error=ConnectionRefusedError(),
        )
    )
    assert _is_network_error(OSError("generic"))
    assert _is_network_error(ConnectionRefusedError())

    assert not _is_network_error(RuntimeError("not network"))
    assert not _is_network_error(ValueError("not network"))
    assert not _is_network_error(Exception("generic"))
