"""Regression tests for QQ channel WebSocket reconnect backoff.

Tests that the overridden ``bot_connect()`` applies exponential backoff and
compact error logging when ``BotWebSocket.ws_connect`` raises a DNS/network
error, instead of the original behavior of immediately re-queuing the session
and dumping a full traceback.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

# Skip all tests if botpy is not installed
pytest.importorskip("botpy")


def _make_channel():
    """Create a minimal QQChannel instance for testing."""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.qq.runtime import QQChannel, QQConfig

    bus = MessageBus()
    config = QQConfig(app_id="test_app", secret="test_secret")
    return QQChannel(config, bus)


def _make_bot(channel):
    """Create the _Bot class and instantiate it with mocked internals."""
    from nanobot.channels.qq.runtime import _make_bot_class

    bot_cls = _make_bot_class(channel)
    bot = bot_cls.__new__(bot_cls)

    # Mock the attributes that bot_connect() needs
    bot._connection = MagicMock()
    bot._connection.add = MagicMock()
    bot._ws_backoff = {}  # per-session dict
    return bot


@pytest.mark.asyncio
async def test_bot_connect_dns_error_applies_backoff():
    """bot_connect() should sleep with exponential backoff on DNS errors."""
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
        patch("asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        mock_client = MagicMock()
        mock_client.ws_connect = AsyncMock(side_effect=dns_error)
        mock_client._conn = None
        mock_ws_cls.return_value = mock_client

        session = {"session_id": "", "url": "wss://example.com/ws"}
        await bot.bot_connect(session)

        # Should have slept (backoff applied)
        mock_sleep.assert_awaited_once_with(5)

        # Backoff should have doubled for this session
        assert bot._ws_backoff[id(session)] == 10

        # Session should have been re-queued
        bot._connection.add.assert_called_once_with(session)


@pytest.mark.asyncio
async def test_bot_connect_dns_error_no_traceback(capsys):
    """bot_connect() should NOT print traceback for DNS/network errors."""
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
        mock_client._conn = None
        mock_ws_cls.return_value = mock_client

        session = {"session_id": "", "url": "wss://example.com/ws"}
        await bot.bot_connect(session)

    # Capture stdout/stderr — should NOT contain traceback
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


@pytest.mark.asyncio
async def test_bot_connect_connector_error_applies_backoff():
    """bot_connect() should apply backoff for ClientConnectorError too."""
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
        mock_client._conn = None
        mock_ws_cls.return_value = mock_client

        session = {"session_id": "", "url": "wss://example.com/ws"}
        await bot.bot_connect(session)

        mock_sleep.assert_awaited_once_with(5)
        assert bot._ws_backoff[id(session)] == 10


@pytest.mark.asyncio
async def test_bot_connect_backoff_doubles_and_caps():
    """Backoff should double on each failure and cap at max_backoff."""
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
        mock_client._conn = None
        mock_ws_cls.return_value = mock_client

        session = {"session_id": "", "url": "wss://example.com/ws"}

        # Simulate multiple failures with the same session
        for expected_backoff in [5, 10, 20, 40, 80, 160, 300, 300]:
            bot._ws_backoff[id(session)] = expected_backoff
            await bot.bot_connect(session)
            # After this call, backoff should have doubled (capped at max)
            expected_next = min(expected_backoff * 2, _RECONNECT_BACKOFF_MAX)
            assert bot._ws_backoff[id(session)] == expected_next


@pytest.mark.asyncio
async def test_bot_connect_success_resets_backoff():
    """bot_connect() should reset backoff on successful connection."""
    channel = _make_channel()
    bot = _make_bot(channel)
    session = {"session_id": "", "url": "wss://example.com/ws"}
    bot._ws_backoff[id(session)] = 80  # was backing off

    with patch("nanobot.channels.qq.runtime.BotWebSocket") as mock_ws_cls:
        mock_client = MagicMock()
        mock_client.ws_connect = AsyncMock()  # succeeds
        mock_client._conn = MagicMock()
        mock_ws_cls.return_value = mock_client

        await bot.bot_connect(session)

        assert id(session) not in bot._ws_backoff  # per-session backoff cleared
        # Session should NOT be re-queued on success
        bot._connection.add.assert_not_called()


@pytest.mark.asyncio
async def test_bot_connect_non_network_error_still_requeues():
    """bot_connect() should still re-queue session for non-network errors."""
    channel = _make_channel()
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
        mock_client._conn = None
        mock_ws_cls.return_value = mock_client

        session = {"session_id": "", "url": "wss://example.com/ws"}
        await bot.bot_connect(session)

        # No backoff sleep for non-network errors
        mock_sleep.assert_not_awaited()

        # Session still re-queued
        bot._connection.add.assert_called_once_with(session)


@pytest.mark.asyncio
async def test_bot_connect_per_session_backoff_isolated():
    """Backoff should be tracked per-session, not shared across sessions."""
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
        mock_client._conn = None
        mock_ws_cls.return_value = mock_client

        session_a = {"session_id": "a", "url": "wss://example.com/ws"}
        session_b = {"session_id": "b", "url": "wss://example.com/ws"}

        # Fail session A once -> backoff 5 -> 10
        await bot.bot_connect(session_a)
        assert bot._ws_backoff[id(session_a)] == 10

        # Fail session B once -> backoff should start at 5, not 10
        await bot.bot_connect(session_b)
        assert bot._ws_backoff[id(session_b)] == 10  # 5 * 2

        # Fail session A again -> should be 20 (10 * 2), not affected by B
        await bot.bot_connect(session_a)
        assert bot._ws_backoff[id(session_a)] == 20

        # Session B still at 10, independent
        assert bot._ws_backoff[id(session_b)] == 10

def test_is_network_error_classification():
    """_is_network_error correctly classifies error types."""
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
