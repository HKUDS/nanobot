"""Tests for ChannelManager.deliver() and _attempt_send() retry logic."""

from __future__ import annotations

from pathlib import Path

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config
from nanobot.errors import DeliverySkippedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeChannel(BaseChannel):
    """Minimal channel stub for testing delivery paths."""

    def __init__(self, *, fail_count: int = 0, error: Exception | None = None):
        self._fail_count = fail_count
        self._error = error or RuntimeError("send error")
        self._attempts = 0
        self._sent: list[OutboundMessage] = []

    @property
    def is_running(self) -> bool:
        return True

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        self._attempts += 1
        if self._attempts <= self._fail_count:
            raise self._error
        self._sent.append(msg)


def _make_manager(tmp_path: Path, channels: dict[str, BaseChannel]) -> ChannelManager:
    """Create a ChannelManager with pre-injected fake channels."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    bus = MessageBus()
    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = config
    mgr.bus = bus
    mgr.channels = dict(channels)
    mgr._dispatch_task = None
    mgr._dead_letter_file = tmp_path / "outbound_failed.jsonl"
    return mgr


def _msg(channel: str = "test", chat_id: str = "u1") -> OutboundMessage:
    return OutboundMessage(channel=channel, chat_id=chat_id, content="hello")


# ---------------------------------------------------------------------------
# Tests: deliver()
# ---------------------------------------------------------------------------


async def test_deliver_success(tmp_path: Path) -> None:
    ch = _FakeChannel()
    mgr = _make_manager(tmp_path, {"test": ch})
    result = await mgr.deliver(_msg())
    assert result.success
    assert result.channel == "test"
    assert result.chat_id == "u1"
    assert len(ch._sent) == 1


async def test_deliver_unknown_channel(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path, {})
    result = await mgr.deliver(_msg("nonexistent"))
    assert not result.success
    assert "Unknown channel" in (result.error or "")


async def test_deliver_catches_delivery_skipped(tmp_path: Path) -> None:
    """deliver() returns failure when channel raises DeliverySkippedError."""
    ch = _FakeChannel(fail_count=999, error=DeliverySkippedError("consent not granted"))
    mgr = _make_manager(tmp_path, {"test": ch})
    result = await mgr.deliver(_msg())
    assert not result.success
    assert "consent not granted" in (result.error or "")


async def test_deliver_catches_runtime_error(tmp_path: Path) -> None:
    ch = _FakeChannel(fail_count=999, error=RuntimeError("socket closed"))
    mgr = _make_manager(tmp_path, {"test": ch})
    result = await mgr.deliver(_msg())
    assert not result.success
    assert "socket closed" in (result.error or "")


# ---------------------------------------------------------------------------
# Tests: _attempt_send() retry behaviour
# ---------------------------------------------------------------------------


async def test_attempt_send_retries_and_succeeds(tmp_path: Path) -> None:
    """Transient failures are retried and delivery succeeds on 2nd attempt."""
    ch = _FakeChannel(fail_count=1)
    mgr = _make_manager(tmp_path, {"test": ch})
    result = await mgr._attempt_send(ch, _msg())
    assert result.success
    assert ch._attempts == 2  # 1 fail + 1 success
    assert len(ch._sent) == 1


async def test_attempt_send_respects_max_attempts(tmp_path: Path) -> None:
    """After max_attempts failures, gives up and returns failure."""
    ch = _FakeChannel(fail_count=999)
    mgr = _make_manager(tmp_path, {"test": ch})
    result = await mgr._attempt_send(ch, _msg(), max_attempts=2)
    assert not result.success
    assert ch._attempts == 2


async def test_attempt_send_writes_dead_letter_on_exhaust(tmp_path: Path) -> None:
    """Failed delivery writes to dead-letter file."""
    ch = _FakeChannel(fail_count=999)
    mgr = _make_manager(tmp_path, {"test": ch})
    await mgr._attempt_send(ch, _msg(), max_attempts=1)
    assert mgr._dead_letter_file.exists()
    content = mgr._dead_letter_file.read_text()
    assert "hello" in content
    assert "send error" in content


async def test_attempt_send_succeeds_on_last_retry(tmp_path: Path) -> None:
    """Fails twice, succeeds on 3rd (last) attempt."""
    ch = _FakeChannel(fail_count=2)
    mgr = _make_manager(tmp_path, {"test": ch})
    result = await mgr._attempt_send(ch, _msg(), max_attempts=3)
    assert result.success
    assert ch._attempts == 3
    # No dead letter written
    assert not mgr._dead_letter_file.exists()


async def test_attempt_send_single_attempt_success(tmp_path: Path) -> None:
    ch = _FakeChannel(fail_count=0)
    mgr = _make_manager(tmp_path, {"test": ch})
    result = await mgr._attempt_send(ch, _msg(), max_attempts=1)
    assert result.success
    assert ch._attempts == 1
