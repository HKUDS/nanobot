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
    """Test that allow_from matching is case-insensitive for email channel."""
    channel = _DummyChannel(SimpleNamespace(allow_from=["Allow@Example.com"]), MessageBus())
    channel.name = "email"

    assert channel.is_allowed("allow@example.com") is True
    assert channel.is_allowed("ALLOW@EXAMPLE.COM") is True
    assert channel.is_allowed("Allow@Example.com") is True
    assert channel.is_allowed("other@example.com") is False


def test_is_allowed_case_sensitive_for_non_email() -> None:
    """Test that allow_from matching remains case-sensitive for non-email channels."""
    channel = _DummyChannel(SimpleNamespace(allow_from=["User123"]), MessageBus())
    channel.name = "telegram"

    assert channel.is_allowed("User123") is True
    assert channel.is_allowed("user123") is False
    assert channel.is_allowed("USER123") is False
