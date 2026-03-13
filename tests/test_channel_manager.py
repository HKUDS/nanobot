import asyncio
from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class _DummyChannel(BaseChannel):
    name = "dummy"
    display_name = "Dummy"

    def __init__(self, config, bus, *, supports_content_stream_progress: bool):
        super().__init__(config, bus)
        self.supports_content_stream_progress = supports_content_stream_progress
        self.sent: list[OutboundMessage] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


async def _run_dispatch_once(manager: ChannelManager, bus: MessageBus, msg: OutboundMessage) -> None:
    task = asyncio.create_task(manager._dispatch_outbound())
    await bus.publish_outbound(msg)
    for _ in range(30):
        if bus.outbound_size == 0:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_content_progress_is_dropped_for_unsupported_channel() -> None:
    bus = MessageBus()
    config = Config()
    manager = ChannelManager(config, bus)
    channel = _DummyChannel(
        SimpleNamespace(allow_from=["*"]),
        bus,
        supports_content_stream_progress=False,
    )
    manager.channels = {"dummy": channel}

    await _run_dispatch_once(
        manager,
        bus,
        OutboundMessage(
            channel="dummy",
            chat_id="chat-1",
            content="he",
            metadata={"_progress": True, "_progress_kind": "content"},
        ),
    )

    assert channel.sent == []


@pytest.mark.asyncio
async def test_content_progress_is_sent_for_supported_channel() -> None:
    bus = MessageBus()
    config = Config()
    manager = ChannelManager(config, bus)
    channel = _DummyChannel(
        SimpleNamespace(allow_from=["*"]),
        bus,
        supports_content_stream_progress=True,
    )
    manager.channels = {"dummy": channel}

    await _run_dispatch_once(
        manager,
        bus,
        OutboundMessage(
            channel="dummy",
            chat_id="chat-1",
            content="he",
            metadata={"_progress": True, "_progress_kind": "content"},
        ),
    )

    assert len(channel.sent) == 1
    assert channel.sent[0].content == "he"
