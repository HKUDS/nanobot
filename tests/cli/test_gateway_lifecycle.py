from nanobot.bus.queue import MessageBus
from nanobot.cli.commands import _notify_gateway_lifecycle


async def test_notify_gateway_lifecycle_publishes_to_picked_target() -> None:
    bus = MessageBus()

    await _notify_gateway_lifecycle(bus, lambda: ("telegram", "1001"), "Gateway online 🟢")

    msg = await bus.consume_outbound()
    assert msg.channel == "telegram"
    assert msg.chat_id == "1001"
    assert msg.content == "Gateway online 🟢"


async def test_notify_gateway_lifecycle_is_noop_for_cli_target() -> None:
    bus = MessageBus()

    await _notify_gateway_lifecycle(bus, lambda: ("cli", "direct"), "Gateway online")

    assert bus.outbound_size == 0
