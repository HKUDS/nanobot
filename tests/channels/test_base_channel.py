from types import SimpleNamespace

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


def test_is_allowed_case_insensitive() -> None:
    """Test that allow_from matching is case-insensitive."""
    channel = _DummyChannel(SimpleNamespace(allow_from=["Allow@Example.com"]), MessageBus())

    assert channel.is_allowed("allow@example.com") is True
    assert channel.is_allowed("ALLOW@EXAMPLE.COM") is True
    assert channel.is_allowed("Allow@Example.com") is True
    assert channel.is_allowed("other@example.com") is False
