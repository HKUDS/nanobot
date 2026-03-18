from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class _DummyChannel(BaseChannel):
    name = "dummy"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        return None


def test_is_allowed_requires_exact_match() -> None:
    channel = _DummyChannel(SimpleNamespace(allow_from=["allow@email.com"]), MessageBus())

    assert channel.is_allowed("allow@email.com") is True
    assert channel.is_allowed("attacker|allow@email.com") is False


@pytest.mark.asyncio
async def test_transcribe_audio_uses_injected_transcriber() -> None:
    channel = _DummyChannel(SimpleNamespace(allow_from=["*"]), MessageBus())
    channel.transcriber = AsyncMock()
    channel.transcriber.transcribe.return_value = "hello"

    assert await channel.transcribe_audio("voice.ogg") == "hello"
    channel.transcriber.transcribe.assert_awaited_once_with("voice.ogg")
