"""Demonstrate the two async queues used by channels and the agent loop."""

import asyncio
from datetime import datetime

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


async def main() -> None:
    bus = MessageBus()
    inbound = InboundMessage(
        channel="lesson",
        sender_id="student",
        chat_id="demo",
        content="hello",
        timestamp=datetime.now(),
    )
    await bus.publish_inbound(inbound)
    received = await bus.consume_inbound()
    await bus.publish_outbound(
        OutboundMessage(channel=received.channel, chat_id=received.chat_id, content="world")
    )
    sent = await bus.consume_outbound()
    print(f"session_key={received.session_key}")
    print(f"outbound={sent.content}")


if __name__ == "__main__":
    asyncio.run(main())
