"""Contract tests: routing applies uniformly across all entry points."""

from __future__ import annotations

from nanobot.bus.events import InboundMessage


def test_inbound_message_has_forced_role_field() -> None:
    """InboundMessage accepts forced_role with None default."""
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello")
    assert msg.forced_role is None

    msg2 = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content="hello",
        forced_role="code",
    )
    assert msg2.forced_role == "code"
