"""Tests for outbound channel dispatching."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class _RecordingChannel(BaseChannel):
    def __init__(self, bus: MessageBus):
        super().__init__(SimpleNamespace(allow_from=["*"]), bus)
        self.sent: list[OutboundMessage] = []

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


@pytest.mark.asyncio
async def test_dispatcher_skips_tool_hints_when_disabled() -> None:
    from nanobot.channels.dispatcher import OutboundDispatcher

    bus = MessageBus()
    config = Config()
    config.channels.send_tool_hints = False
    channel = _RecordingChannel(bus)
    dispatcher = OutboundDispatcher(config, bus, {"telegram": channel})

    task = asyncio.create_task(dispatcher.run())
    await bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="chat-1",
            content='read_file("foo.txt")',
            metadata={"_progress": True, "_tool_hint": True},
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    await task

    assert channel.sent == []


@pytest.mark.asyncio
async def test_dispatcher_skips_progress_when_disabled() -> None:
    from nanobot.channels.dispatcher import OutboundDispatcher

    bus = MessageBus()
    config = Config()
    config.channels.send_progress = False
    channel = _RecordingChannel(bus)
    dispatcher = OutboundDispatcher(config, bus, {"telegram": channel})

    task = asyncio.create_task(dispatcher.run())
    await bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="chat-1",
            content="Thinking...",
            metadata={"_progress": True},
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    await task

    assert channel.sent == []


@pytest.mark.asyncio
async def test_dispatcher_sends_non_progress_messages_to_matching_channel() -> None:
    from nanobot.channels.dispatcher import OutboundDispatcher

    bus = MessageBus()
    config = Config()
    channel = _RecordingChannel(bus)
    dispatcher = OutboundDispatcher(config, bus, {"telegram": channel})

    task = asyncio.create_task(dispatcher.run())
    message = OutboundMessage(channel="telegram", chat_id="chat-1", content="hello")
    await bus.publish_outbound(message)
    await asyncio.sleep(0)
    task.cancel()
    await task

    assert channel.sent == [message]


@pytest.mark.asyncio
async def test_channel_manager_uses_outbound_dispatcher(monkeypatch) -> None:
    bus = MessageBus()
    config = Config()
    events: list[object] = []

    class FakeDispatcher:
        def __init__(self, runtime_config, runtime_bus, channels):
            events.append((runtime_config, runtime_bus, channels))

        async def run(self) -> None:
            events.append("run")

    class FakeFactory:
        def build_enabled_channels(self, runtime_config, runtime_bus):
            return {"telegram": _RecordingChannel(runtime_bus)}

    monkeypatch.setattr("nanobot.channels.manager.OutboundDispatcher", FakeDispatcher)
    monkeypatch.setattr("nanobot.channels.manager.BuiltinChannelFactory", FakeFactory)

    manager = ChannelManager(config, bus)
    await manager.start_all()

    assert events == [(config, bus, manager.channels), "run"]
