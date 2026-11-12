import asyncio
from unittest.mock import AsyncMock, MagicMock

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels import manager as manager_module
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


def make_manager():
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    manager = ChannelManager(config, MessageBus())
    channel = MagicMock(spec=BaseChannel)
    channel.send = AsyncMock()
    channel.stop = AsyncMock()
    manager.channels["websocket"] = channel
    return manager, channel


async def wait_until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


async def test_ten_chats_keep_order_while_one_destination_is_blocked():
    manager, channel = make_manager()
    release = asyncio.Event()
    started = asyncio.Event()
    received = {str(i): [] for i in range(10)}

    async def send(msg):
        if msg.chat_id == "0":
            started.set()
            await release.wait()
        received[msg.chat_id].append(msg.content)

    channel.send.side_effect = send
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())
    try:
        for content in ("first", "last"):
            for i in range(10):
                await manager.bus.publish_outbound(OutboundMessage("websocket", str(i), content))
        await asyncio.wait_for(started.wait(), 2)
        await wait_until(lambda: all(len(received[str(i)]) == 2 for i in range(1, 10)))
        assert received["0"] == []
        assert all(received[str(i)] == ["first", "last"] for i in range(1, 10))
        release.set()
        await wait_until(lambda: not manager._outbound_tasks)
        assert received["0"] == ["first", "last"]
        assert manager._outbound_tails == {}
    finally:
        await manager.stop_all()


async def test_retry_does_not_block_other_chats(monkeypatch):
    monkeypatch.setattr(manager_module, "_SEND_RETRY_DELAYS", (0.1,))
    manager, channel = make_manager()
    retry_started = asyncio.Event()
    healthy_sent = asyncio.Event()
    attempts = 0

    async def send(msg):
        nonlocal attempts
        if msg.chat_id == "retry":
            attempts += 1
            if attempts == 1:
                retry_started.set()
                raise OSError("temporary failure")
            assert healthy_sent.is_set()
        else:
            healthy_sent.set()

    channel.send.side_effect = send
    channel.should_retry_send_error.return_value = True
    try:
        await manager._queue_outbound(channel, OutboundMessage("websocket", "retry", "a"))
        await asyncio.wait_for(retry_started.wait(), 2)
        await manager._queue_outbound(channel, OutboundMessage("websocket", "healthy", "b"))
        await wait_until(lambda: not manager._outbound_tasks)
        assert attempts == 2
        assert healthy_sent.is_set()
    finally:
        await manager._cancel_outbound()


async def test_pending_and_concurrent_sends_are_bounded_and_cancellable(monkeypatch):
    monkeypatch.setattr(manager_module, "_OUTBOUND_PENDING_LIMIT", 4)
    monkeypatch.setattr(manager_module, "_OUTBOUND_CONCURRENCY", 2)
    manager, channel = make_manager()
    blocked = asyncio.Event()
    active = 0
    peak = 0

    async def send(msg):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await blocked.wait()
        finally:
            active -= 1

    channel.send.side_effect = send
    for i in range(4):
        await manager._queue_outbound(channel, OutboundMessage("websocket", str(i), "a"))
    extra = asyncio.create_task(manager._queue_outbound(
        channel, OutboundMessage("websocket", "extra", "a"),
    ))
    try:
        await wait_until(lambda: active == 2)
        assert not extra.done()
        assert len(manager._outbound_tasks) == 4
        extra.cancel()
        await asyncio.gather(extra, return_exceptions=True)
        await manager._cancel_outbound()
        assert peak == 2
        assert active == 0
        assert not manager._outbound_tasks
        assert not manager._outbound_tails
        # Cancellation returns admission permits, including tasks not yet sending.
        for i in range(4):
            await asyncio.wait_for(manager._queue_outbound(
                channel, OutboundMessage("websocket", str(i), "b"),
            ), 2)
    finally:
        extra.cancel()
        await asyncio.gather(extra, return_exceptions=True)
        await manager._cancel_outbound()


async def test_channel_stop_cancels_only_its_sends_before_stopping_runtime():
    manager, channel = make_manager()
    active = asyncio.Event()
    cancelled = asyncio.Event()

    async def send(msg):
        active.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def stop():
        assert cancelled.is_set()

    channel.send.side_effect = send
    channel.stop.side_effect = stop
    other = MagicMock(spec=BaseChannel)
    other.send = AsyncMock()
    manager.channels["other"] = other
    await manager._queue_outbound(channel, OutboundMessage("websocket", "a", "1"))
    await asyncio.wait_for(active.wait(), 2)
    await manager._stop_channel("websocket")
    await manager._queue_outbound(other, OutboundMessage("other", "b", "2"))
    await wait_until(lambda: not manager._outbound_tasks)
    other.send.assert_awaited_once()
    assert not manager._outbound_tails


async def test_dispatcher_shutdown_cleans_active_and_waiting_destination_tasks():
    manager, channel = make_manager()
    active = asyncio.Event()
    cancelled = asyncio.Event()

    async def send(msg):
        active.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    channel.send.side_effect = send
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())
    try:
        for content in ("one", "two", "three"):
            await manager.bus.publish_outbound(OutboundMessage("websocket", "chat", content))
        await asyncio.wait_for(active.wait(), 2)
        await wait_until(lambda: len(manager._outbound_tasks) == 3)
    finally:
        await manager.stop_all()
    assert cancelled.is_set()
    channel.send.assert_awaited_once()
    assert not manager._outbound_tasks
    assert not manager._outbound_tails
