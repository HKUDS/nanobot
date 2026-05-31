"""Tests for the delivery-future plumbing that lets MessageTool report actual
send outcomes instead of fire-and-forget claiming success.

Triggered by the 2026-05-30 21:53 incident: Peewee told Steve "Message sent to
Ruth on Telegram!" even though the underlying send failed with "Chat not
found" (Ruth hadn't /started the bot yet)."""

from __future__ import annotations

import asyncio

import pytest

from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage


@pytest.mark.asyncio
async def test_tool_reports_real_error_when_dispatcher_fails() -> None:
    sent: list[OutboundMessage] = []

    async def cb(msg):
        sent.append(msg)
        # Mirror the dispatcher: real send raised → resolve future with the
        # exception so MessageTool can surface it.
        msg.delivery_future.set_exception(RuntimeError("Chat not found"))

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
    )
    result = await tool.execute(content="hi", channel="telegram", chat_id="9999")

    assert "Error sending message" in result
    assert "Chat not found" in result
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_tool_reports_success_when_dispatcher_resolves_with_none() -> None:
    sent: list[OutboundMessage] = []

    async def cb(msg):
        sent.append(msg)
        msg.delivery_future.set_result(None)

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
    )
    result = await tool.execute(content="hi")

    assert result.startswith("Message sent to telegram:12345")


@pytest.mark.asyncio
async def test_tool_reports_pending_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the dispatcher takes longer than the timeout to confirm, the tool
    must return a 'not confirmed' result rather than falsely claim success."""
    monkeypatch.setattr("nanobot.agent.tools.message._DELIVERY_TIMEOUT_S", 0.05)

    async def cb(msg):
        pass  # never resolve the future

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
    )
    result = await tool.execute(content="hi")
    assert "not confirmed" in result.lower()


@pytest.mark.asyncio
async def test_message_carries_delivery_future_to_dispatcher() -> None:
    """The OutboundMessage handed to the send callback must have a
    delivery_future attached so the dispatcher can resolve it."""
    captured: list[OutboundMessage] = []

    async def cb(msg):
        captured.append(msg)
        msg.delivery_future.set_result(None)

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
    )
    await tool.execute(content="hi")

    assert captured
    assert captured[0].delivery_future is not None
    assert isinstance(captured[0].delivery_future, asyncio.Future)
    assert captured[0].delivery_future.done()


@pytest.mark.asyncio
async def test_dispatcher_resolves_future_on_success() -> None:
    """When the channel.send succeeds, the dispatcher sets the future's result.
    Covers the success path through ChannelManager._dispatch_outbound."""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.base import BaseChannel
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.schema import Config

    class _OKChannel(BaseChannel):
        def __init__(self): pass
        async def start(self): pass
        async def stop(self): pass
        async def send(self, msg): return None

    bus = MessageBus()
    cfg = Config()
    mgr = ChannelManager(cfg, bus)
    mgr.channels["fake"] = _OKChannel()
    # Don't start the full manager; run one dispatch pass directly.
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    await bus.publish_outbound(OutboundMessage(channel="fake", chat_id="x", content="hi", delivery_future=fut))

    # Run the dispatcher for a brief moment.
    task = asyncio.create_task(mgr._dispatch_outbound())
    try:
        await asyncio.wait_for(fut, timeout=2.0)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert fut.done()
    assert fut.exception() is None


@pytest.mark.asyncio
async def test_dispatcher_resolves_future_on_send_exception() -> None:
    """When the channel.send raises, the dispatcher sets the future's
    exception so MessageTool can surface it."""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.base import BaseChannel
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.schema import Config

    class _FailingChannel(BaseChannel):
        def __init__(self): pass
        async def start(self): pass
        async def stop(self): pass
        async def send(self, msg):
            raise RuntimeError("Chat not found")

    bus = MessageBus()
    cfg = Config()
    mgr = ChannelManager(cfg, bus)
    mgr.channels["telegram"] = _FailingChannel()

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    await bus.publish_outbound(OutboundMessage(channel="telegram", chat_id="x", content="hi", delivery_future=fut))

    task = asyncio.create_task(mgr._dispatch_outbound())
    try:
        with pytest.raises(RuntimeError, match="Chat not found"):
            await asyncio.wait_for(fut, timeout=2.0)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_dispatcher_handles_message_without_future() -> None:
    """Backward compatibility: messages without a delivery_future must still
    dispatch without error (legacy publishers don't attach one)."""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.base import BaseChannel
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.schema import Config

    delivered: list[OutboundMessage] = []

    class _RecordingChannel(BaseChannel):
        def __init__(self): pass
        async def start(self): pass
        async def stop(self): pass
        async def send(self, msg):
            delivered.append(msg)

    bus = MessageBus()
    cfg = Config()
    mgr = ChannelManager(cfg, bus)
    mgr.channels["any"] = _RecordingChannel()

    # No delivery_future set (default None)
    await bus.publish_outbound(OutboundMessage(channel="any", chat_id="x", content="hi"))

    task = asyncio.create_task(mgr._dispatch_outbound())
    try:
        for _ in range(20):
            await asyncio.sleep(0.05)
            if delivered:
                break
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert len(delivered) == 1
