from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager


@pytest.mark.asyncio
async def test_message_tool_waits_for_delivery_ack() -> None:
    delivered: list[OutboundMessage] = []

    async def send_callback(msg: OutboundMessage) -> None:
        delivered.append(msg)
        assert msg.delivery_future is not None
        msg.delivery_future.set_result(None)

    tool = MessageTool(send_callback=send_callback, default_channel="feishu", default_chat_id="chat1")
    result = await tool.execute(content="hello")

    assert result == "Message sent to feishu:chat1"
    assert len(delivered) == 1
    assert tool._sent_in_turn is True


@pytest.mark.asyncio
async def test_message_tool_returns_dispatch_error() -> None:
    async def send_callback(msg: OutboundMessage) -> None:
        assert msg.delivery_future is not None
        msg.delivery_future.set_exception(RuntimeError("boom"))

    tool = MessageTool(send_callback=send_callback, default_channel="feishu", default_chat_id="chat1")
    result = await tool.execute(content="hello")

    assert result == "Error sending message: boom"
    assert tool._sent_in_turn is False


class _FakeChannel:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.sent: list[OutboundMessage] = []

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)
        if self.error is not None:
            raise self.error


def _make_manager(*, send_progress: bool = True, send_tool_hints: bool = False) -> ChannelManager:
    manager = ChannelManager.__new__(ChannelManager)
    manager.config = SimpleNamespace(
        channels=SimpleNamespace(send_progress=send_progress, send_tool_hints=send_tool_hints)
    )
    manager.bus = MessageBus()
    manager.channels = {}
    manager._dispatch_task = None
    return manager


@pytest.mark.asyncio
async def test_dispatch_resolves_delivery_future_on_success() -> None:
    manager = _make_manager()
    channel = _FakeChannel()
    manager.channels["feishu"] = channel
    msg = OutboundMessage(
        channel="feishu",
        chat_id="chat1",
        content="hello",
        delivery_future=asyncio.get_running_loop().create_future(),
    )

    await manager.bus.publish_outbound(msg)
    task = asyncio.create_task(manager._dispatch_outbound())
    await asyncio.wait_for(msg.delivery_future, timeout=1.0)
    task.cancel()
    await task

    assert channel.sent == [msg]


@pytest.mark.asyncio
async def test_dispatch_resolves_delivery_future_on_failure() -> None:
    manager = _make_manager()
    manager.channels["feishu"] = _FakeChannel(RuntimeError("send failed"))
    msg = OutboundMessage(
        channel="feishu",
        chat_id="chat1",
        content="hello",
        delivery_future=asyncio.get_running_loop().create_future(),
    )

    await manager.bus.publish_outbound(msg)
    task = asyncio.create_task(manager._dispatch_outbound())
    with pytest.raises(RuntimeError, match="send failed"):
        await asyncio.wait_for(msg.delivery_future, timeout=1.0)
    task.cancel()
    await task


@pytest.mark.asyncio
async def test_dispatch_resolves_delivery_future_for_unknown_channel() -> None:
    manager = _make_manager()
    msg = OutboundMessage(
        channel="missing",
        chat_id="chat1",
        content="hello",
        delivery_future=asyncio.get_running_loop().create_future(),
    )

    await manager.bus.publish_outbound(msg)
    task = asyncio.create_task(manager._dispatch_outbound())
    with pytest.raises(RuntimeError, match="Unknown channel: missing"):
        await asyncio.wait_for(msg.delivery_future, timeout=1.0)
    task.cancel()
    await task


@pytest.mark.asyncio
async def test_dispatch_resolves_suppressed_progress_delivery_future() -> None:
    manager = _make_manager(send_progress=False)
    msg = OutboundMessage(
        channel="feishu",
        chat_id="chat1",
        content="hello",
        metadata={"_progress": True},
        delivery_future=asyncio.get_running_loop().create_future(),
    )

    await manager.bus.publish_outbound(msg)
    task = asyncio.create_task(manager._dispatch_outbound())
    await asyncio.wait_for(msg.delivery_future, timeout=1.0)
    task.cancel()
    await task
