import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels import manager as manager_module
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config
from nanobot.runtime_admission import RuntimeBusyError


def make_manager():
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    manager = ChannelManager(config, MessageBus())
    channel = MagicMock(spec=BaseChannel)
    channel.send = AsyncMock()
    channel.stop = AsyncMock()
    channel.has_pending_delivery = False
    manager.channels["websocket"] = channel
    return manager, channel


async def test_delivery_has_no_idle_gap_between_queue_dispatch_and_send(monkeypatch):
    manager, channel = make_manager()
    started, release = asyncio.Event(), asyncio.Event()
    observations = []
    consume = manager.bus.consume_outbound

    def require_busy():
        if manager.bus.admission.paused:
            observations.append("parked")
            return
        with pytest.raises(RuntimeBusyError):
            with manager.bus.admission.pause_if_idle(lambda: False):
                pytest.fail("Delivery was incorrectly reported idle")
        observations.append("busy")
        assert not manager.bus.admission.paused

    async def dequeue():
        message = await consume()
        asyncio.get_running_loop().call_soon(require_busy)
        return message

    async def send(message):
        started.set()
        await release.wait()

    monkeypatch.setattr(manager.bus, "consume_outbound", dequeue)
    channel.send.side_effect = send
    await manager.bus.publish_outbound(OutboundMessage("websocket", "chat", "final reply"))
    require_busy()
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert manager.bus.outbound_size == 0
        require_busy()
        assert observations == ["busy", "busy", "busy"]
        release.set()
        await wait_until(lambda: not manager.has_pending_delivery)
        with manager.bus.admission.pause_if_idle(lambda: False):
            assert manager.bus.admission.paused
            # A late producer may queue a lifecycle notice while the consumer
            # is awaiting an empty queue. It must remain parked until admission
            # is restored, rather than start new transport writes under the gate.
            await manager.bus.publish_outbound(OutboundMessage("websocket", "chat", "late notice"))
            await wait_until(lambda: manager._outbound_dispatching)
            await wait_until(lambda: len(observations) == 4)
            channel.send.assert_awaited_once()
        assert not manager.bus.admission.paused
        await wait_until(lambda: not manager.has_pending_delivery)
        assert [call.args[0].content for call in channel.send.await_args_list] == ["final reply", "late notice"]
        assert observations == ["busy", "busy", "busy", "parked"]
    finally:
        release.set()
        await manager.stop_all()


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


async def test_all_send_slots_in_backoff_leave_healthy_chat_and_fifo_live(monkeypatch):
    monkeypatch.setattr(manager_module, "_SEND_RETRY_DELAYS", (0.6,))
    manager, channel = make_manager()
    failed = set()
    delivered = []

    async def send(msg):
        if msg.chat_id != "healthy" and msg.chat_id not in failed:
            failed.add(msg.chat_id)
            raise OSError("temporary failure")
        delivered.append((msg.chat_id, msg.content))

    channel.send.side_effect = send
    channel.should_retry_send_error.return_value = True
    try:
        for i in range(manager_module._OUTBOUND_CONCURRENCY):
            await manager._queue_outbound(channel, OutboundMessage("websocket", str(i), "first"))
        await wait_until(lambda: len(failed) == manager_module._OUTBOUND_CONCURRENCY)
        await manager._queue_outbound(channel, OutboundMessage("websocket", "0", "last"))
        await manager._queue_outbound(channel, OutboundMessage("websocket", "healthy", "ok"))
        async with asyncio.timeout(0.2):
            while ("healthy", "ok") not in delivered:
                await asyncio.sleep(0)
        assert ("0", "last") not in delivered
        await wait_until(lambda: not manager._outbound_tasks)
        assert [content for chat, content in delivered if chat == "0"] == ["first", "last"]
    finally:
        await manager._cancel_outbound()
    assert not manager._outbound_tails


async def test_scheduled_cancel_waiting_for_permit_does_not_claim(tmp_path, monkeypatch):
    from nanobot.bus.delivery import DeliveryRequest

    monkeypatch.setattr(manager_module, "_OUTBOUND_CONCURRENCY", 1)
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    manager = ChannelManager(config, MessageBus(), config_path=tmp_path / "config.json")
    channel = MagicMock(spec=BaseChannel, send=AsyncMock())
    manager.channels["websocket"] = channel
    msg = OutboundMessage("websocket", "scheduled", "result",
                          delivery=DeliveryRequest("run", "websocket:scheduled", None))
    manager._outbox.record(msg)
    claim = MagicMock(wraps=manager._outbox.claim)
    monkeypatch.setattr(manager._outbox, "claim", claim)
    await manager._outbound_sends.acquire()
    try:
        await manager._queue_outbound(channel, msg)
        await asyncio.sleep(0)
        await manager._cancel_outbound()
        claim.assert_not_called()
        channel.send.assert_not_awaited()
        assert [item.delivery_id for item in manager._outbox.ready()] == [msg.delivery_id]
        assert not manager._scheduled_deliveries
    finally:
        manager._outbound_sends.release()
        await manager._cancel_outbound()


async def test_restart_notice_does_not_outwait_send_permit_deadline(tmp_path):
    from nanobot.utils.restart import RestartNotice

    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    manager = ChannelManager(config, MessageBus(), config_path=tmp_path / "config.json")
    channel = MagicMock(spec=BaseChannel, is_running=True)
    active = 0
    release = asyncio.Event()
    notices = []

    async def send(msg):
        nonlocal active
        if msg.chat_id == "notice":
            notices.append(msg)
            return
        active += 1
        try:
            await release.wait()
        finally:
            active -= 1

    channel.send = AsyncMock(side_effect=send)
    manager.channels["probe"] = channel
    try:
        for i in range(manager_module._OUTBOUND_CONCURRENCY):
            await manager._queue_outbound(channel, OutboundMessage("probe", str(i), "blocked"))
        await wait_until(lambda: active == manager_module._OUTBOUND_CONCURRENCY)
        await asyncio.wait_for(manager._send_restart_notice_when_started(
            RestartNotice(channel="probe", chat_id="notice", started_at_raw=""), timeout_s=0.05,
        ), 1)
        assert notices == []
        assert active == manager_module._OUTBOUND_CONCURRENCY
    finally:
        await manager._cancel_outbound()
    assert active == 0
    assert manager._outbound_sends._value == manager_module._OUTBOUND_CONCURRENCY


async def test_restart_notice_deadline_does_not_cancel_submitted_send(tmp_path):
    from nanobot.utils.restart import RestartNotice

    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    manager = ChannelManager(config, MessageBus(), config_path=tmp_path / "config.json")
    started = asyncio.Event()
    release = asyncio.Event()

    async def send(msg):
        started.set()
        await release.wait()

    channel = MagicMock(spec=BaseChannel, is_running=True, send=AsyncMock(side_effect=send))
    manager.channels["probe"] = channel
    task = asyncio.create_task(manager._send_restart_notice_when_started(
        RestartNotice(channel="probe", chat_id="notice", started_at_raw=""), timeout_s=0.05,
    ))
    try:
        await asyncio.wait_for(started.wait(), 1)
        try:
            await asyncio.wait_for(asyncio.shield(task), 0.1)
        except TimeoutError:
            pass
        assert not task.done()
        release.set()
        await asyncio.wait_for(task, 1)
        channel.send.assert_awaited_once()
        assert manager._outbound_sends._value == manager_module._OUTBOUND_CONCURRENCY
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
