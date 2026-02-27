"""Fixtures for orghi tests."""

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class RecordingChannel(BaseChannel):
    """Channel that records start() and send() calls for testing."""

    name = "recording"

    def __init__(self, bus: MessageBus, channel_name: str = "recording"):
        super().__init__(object(), bus)
        self.channel_name = channel_name
        self.start_calls: list[tuple[tuple, dict]] = []

    async def start(self, *args: object, **kwargs: object) -> None:
        self.start_calls.append((args, dict(kwargs)))
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        pass


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus()


@pytest.fixture
def recording_telegram(bus: MessageBus) -> RecordingChannel:
    return RecordingChannel(bus, "telegram")


@pytest.fixture
def recording_discord(bus: MessageBus) -> RecordingChannel:
    return RecordingChannel(bus, "discord")
