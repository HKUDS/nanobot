"""Tests for nanobot/channels/retry.py and ChannelHealth integration."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nanobot.channels.retry import ChannelHealth, connection_loop, is_transient, retry_send

# ---------------------------------------------------------------------------
# ChannelHealth
# ---------------------------------------------------------------------------


def test_channel_health_defaults() -> None:
    h = ChannelHealth()
    assert h.healthy is True
    assert h.consecutive_failures == 0
    assert h.last_error is None
    assert h.last_success_at is None
    assert h.last_failure_at is None


def test_channel_health_record_success() -> None:
    h = ChannelHealth()
    h.record_failure(RuntimeError("x"))
    assert h.healthy is False
    assert h.consecutive_failures == 1

    h.record_success()
    assert h.healthy is True
    assert h.consecutive_failures == 0
    assert h.last_success_at is not None


def test_channel_health_record_failure() -> None:
    h = ChannelHealth()
    h.record_failure(RuntimeError("first"))
    h.record_failure(RuntimeError("second"))
    assert h.consecutive_failures == 2
    assert h.last_error == "second"
    assert h.last_failure_at is not None


# ---------------------------------------------------------------------------
# is_transient
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc,expected",
    [
        (ConnectionError("reset"), True),
        (TimeoutError("timed out"), True),
        (asyncio.TimeoutError(), True),
        (OSError("network unreachable"), True),
        (RuntimeError("HTTP 502 bad gateway"), True),
        (RuntimeError("rate limit exceeded"), True),
        (RuntimeError("HTTP 429"), True),
        (ValueError("missing field"), False),
        (KeyError("x"), False),
        (RuntimeError("invalid auth"), False),
    ],
)
def test_is_transient(exc: Exception, expected: bool) -> None:
    assert is_transient(exc) is expected


# ---------------------------------------------------------------------------
# connection_loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_loop_reconnects_on_error() -> None:
    """connection_loop retries after transient errors with backoff."""
    call_count = 0

    async def _connect() -> None:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("reset")
        # On third call, succeed and "stay connected" briefly
        # Then the running_flag turns off

    running = True

    def _flag() -> bool:
        nonlocal running
        if call_count >= 3:
            running = False
        return running

    await connection_loop(
        "test",
        _connect,
        running_flag=_flag,
        min_delay=0.01,
        max_delay=0.05,
    )

    assert call_count == 3


@pytest.mark.asyncio
async def test_connection_loop_stops_on_cancelled() -> None:
    """connection_loop exits cleanly on CancelledError."""

    async def _connect() -> None:
        raise asyncio.CancelledError()

    await connection_loop(
        "test",
        _connect,
        running_flag=lambda: True,
        min_delay=0.01,
    )
    # Should exit without errors


@pytest.mark.asyncio
async def test_connection_loop_stops_when_flag_false() -> None:
    """connection_loop stops when running_flag returns False."""
    call_count = 0

    async def _connect() -> None:
        nonlocal call_count
        call_count += 1

    await connection_loop(
        "test",
        _connect,
        running_flag=lambda: call_count < 1,
        min_delay=0.01,
    )

    assert call_count == 1


# ---------------------------------------------------------------------------
# BaseChannel health integration
# ---------------------------------------------------------------------------


def test_base_channel_has_health() -> None:
    """BaseChannel exposes a ChannelHealth instance."""
    from nanobot.channels.base import BaseChannel

    class _TestChannel(BaseChannel):
        name = "test"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: object) -> None:
            pass

    ch = _TestChannel(SimpleNamespace(), SimpleNamespace(publish_inbound=None))
    assert isinstance(ch.health, ChannelHealth)
    assert ch.health.healthy is True


# ---------------------------------------------------------------------------
# retry_send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_send_success_first_try() -> None:
    """retry_send records success on first call."""
    h = ChannelHealth()
    calls = 0

    async def _ok() -> None:
        nonlocal calls
        calls += 1

    await retry_send(_ok, channel_name="test", health=h)
    assert calls == 1
    assert h.healthy is True
    assert h.last_success_at is not None


@pytest.mark.asyncio
async def test_retry_send_retries_transient_errors() -> None:
    """retry_send retries transient errors up to max_attempts."""
    h = ChannelHealth()
    calls = 0

    async def _fail_then_ok() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("reset")

    await retry_send(
        _fail_then_ok, channel_name="test", health=h, max_attempts=3, base_delay=0.01
    )
    assert calls == 3
    assert h.healthy is True


@pytest.mark.asyncio
async def test_retry_send_raises_non_transient_immediately() -> None:
    """retry_send does not retry non-transient errors."""
    h = ChannelHealth()
    calls = 0

    async def _fatal() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await retry_send(_fatal, channel_name="test", health=h)
    assert calls == 1
    assert h.healthy is False


@pytest.mark.asyncio
async def test_retry_send_raises_after_max_attempts() -> None:
    """retry_send raises after exhausting retries on transient errors."""
    calls = 0

    async def _always_fail() -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError("reset")

    with pytest.raises(ConnectionError):
        await retry_send(_always_fail, channel_name="test", max_attempts=2, base_delay=0.01)
    assert calls == 2


@pytest.mark.asyncio
async def test_retry_send_no_health() -> None:
    """retry_send works without a health tracker."""

    async def _ok() -> None:
        pass

    await retry_send(_ok, channel_name="test")  # no health kwarg
