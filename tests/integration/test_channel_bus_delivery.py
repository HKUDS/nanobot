"""IT-07: MessageBus -> BaseChannel outbound delivery.

Verifies that outbound messages flow through the bus and reach a real
BaseChannel subclass, preserving FIFO order and updating health tracking.

Does not require LLM API key.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Stub channel that records every sent message
# ---------------------------------------------------------------------------


@dataclass
class _ChannelConfig:
    """Minimal config object accepted by BaseChannel."""

    allow_from: list[str] = field(default_factory=list)


class StubChannel(BaseChannel):
    """Concrete BaseChannel that captures outbound messages in a list."""

    name: str = "stub"

    def __init__(self, bus: MessageBus, *, fail_on: set[str] | None = None) -> None:
        super().__init__(_ChannelConfig(), bus)
        self.sent: list[OutboundMessage] = []
        self._fail_on = fail_on or set()

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        if msg.content in self._fail_on:
            raise RuntimeError(f"Simulated send failure for: {msg.content}")
        self.sent.append(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _outbound(content: str, channel: str = "stub", chat_id: str = "test-chat") -> OutboundMessage:
    return OutboundMessage(channel=channel, chat_id=chat_id, content=content)


async def _deliver(bus: MessageBus, channel: StubChannel, messages: list[OutboundMessage]) -> None:
    """Publish messages then consume and deliver them through the channel."""
    for msg in messages:
        await bus.publish_outbound(msg)

    for _ in messages:
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
        try:
            await channel.send(out)
            channel.health.record_success()
        except Exception as exc:
            channel.health.record_failure(exc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOutboundDelivery:
    async def test_single_message_delivered(self) -> None:
        """A single outbound message reaches the stub channel."""
        bus = MessageBus()
        ch = StubChannel(bus)
        msg = _outbound("hello")

        await _deliver(bus, ch, [msg])

        assert len(ch.sent) == 1
        assert ch.sent[0].content == "hello"

    async def test_fifo_ordering_preserved(self) -> None:
        """Messages arrive in the order they were published."""
        bus = MessageBus()
        ch = StubChannel(bus)
        messages = [_outbound(f"msg-{i}") for i in range(5)]

        await _deliver(bus, ch, messages)

        assert len(ch.sent) == 5
        for i, sent in enumerate(ch.sent):
            assert sent.content == f"msg-{i}"


class TestHealthTracking:
    async def test_success_updates_health(self) -> None:
        """Successful delivery records health as healthy."""
        bus = MessageBus()
        ch = StubChannel(bus)

        await _deliver(bus, ch, [_outbound("ok")])

        assert ch.health.healthy is True
        assert ch.health.consecutive_failures == 0
        assert ch.health.last_success_at is not None

    async def test_failure_updates_health(self) -> None:
        """Failed delivery marks channel unhealthy and increments failure count."""
        bus = MessageBus()
        ch = StubChannel(bus, fail_on={"bad-msg"})

        await _deliver(bus, ch, [_outbound("bad-msg")])

        assert ch.health.healthy is False
        assert ch.health.consecutive_failures == 1
        assert ch.health.last_error is not None
        assert "Simulated send failure" in ch.health.last_error

    async def test_recovery_after_failure(self) -> None:
        """A success after failure resets health to healthy."""
        bus = MessageBus()
        ch = StubChannel(bus, fail_on={"fail"})

        await _deliver(bus, ch, [_outbound("fail")])
        assert ch.health.healthy is False
        assert ch.health.consecutive_failures == 1

        await _deliver(bus, ch, [_outbound("recover")])
        assert ch.health.healthy is True
        assert ch.health.consecutive_failures == 0

    async def test_consecutive_failures_accumulate(self) -> None:
        """Multiple failures increment the counter."""
        bus = MessageBus()
        ch = StubChannel(bus, fail_on={"f1", "f2", "f3"})

        await _deliver(bus, ch, [_outbound("f1"), _outbound("f2"), _outbound("f3")])

        assert ch.health.consecutive_failures == 3
        assert ch.health.healthy is False
