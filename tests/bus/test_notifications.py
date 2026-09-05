import asyncio
from dataclasses import dataclass

import pytest

from nanobot.agent.turn_delivery import TurnDeliveryFactory, TurnRoute
from nanobot.bus.events import InboundMessage
from nanobot.bus.notification_delivery import NOTIFICATION_AUDIENCES
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import NotificationPublished, RuntimeEventBus
from nanobot.events import AgentEvent, ContextCompactionEvent, EventSink, RetryWaitEvent
from nanobot.webui.outbound_wire import project_notification


async def test_sink_isolates_observer_failure_but_propagates_cancellation():
    async def broken(event):
        raise ValueError("observer failed")

    await EventSink(broken).emit(AgentEvent())

    async def cancelled(event):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await EventSink(cancelled).emit(AgentEvent())


async def test_scope_snapshots_route_and_queues_before_observers():
    bus, runtime = MessageBus(), RuntimeEventBus()
    metadata = {"slack": {"thread_ts": "original"}}
    factory = TurnDeliveryFactory(bus, runtime)
    delivery = factory.create(InboundMessage(
        channel="slack", sender_id="u", chat_id="chat", content="", metadata=metadata,
    ), "unified:default")
    observed = []

    def observe(notification):
        assert bus.outbound.qsize() == len(observed) + 1
        observed.append(notification)

    runtime.subscribe(observe, NotificationPublished)
    metadata["slack"]["thread_ts"] = "moved"
    for phase in ("started", "succeeded"):
        await delivery.events.emit(ContextCompactionEvent("c1", phase))
    assert len(observed) == 2
    for _ in range(2):
        assert bus.outbound.get_nowait().metadata == {"slack": {"thread_ts": "original"}}


async def test_new_internal_event_needs_explicit_audience(monkeypatch):
    @dataclass(frozen=True)
    class RetryStatus(AgentEvent):
        state: str = "waiting"
        attempt: int = 1

    bus, runtime = MessageBus(), RuntimeEventBus()
    factory = TurnDeliveryFactory(bus, runtime)
    delivery = factory.create(InboundMessage(
        channel="websocket", sender_id="u", chat_id="chat", content="",
    ), "websocket:chat")
    observed = []
    runtime.subscribe(observed.append, NotificationPublished)
    event = RetryStatus()
    await delivery.events.emit(event)
    assert bus.outbound.empty()
    assert observed[-1].event is event
    assert project_notification("chat", event) is None

    monkeypatch.setitem(NOTIFICATION_AUDIENCES, RetryStatus, "interactive")
    await delivery.events.emit(event)
    assert bus.outbound.get_nowait().event is event
    # Routing registration alone does not authorize serialization of private fields.
    assert project_notification("chat", event) is None


async def test_background_scope_keeps_retry_quiet_but_delivers_compaction():
    bus = MessageBus()
    factory = TurnDeliveryFactory(bus, RuntimeEventBus(),
                                  lambda *_: TurnRoute("websocket", "chat"))
    delivery = factory.create(InboundMessage(
        channel="system", sender_id="job", chat_id="websocket:chat", content="",
    ), "websocket:chat")
    await delivery.events.emit(RetryWaitEvent("waiting"))
    assert bus.outbound.empty()
    event = ContextCompactionEvent("c1", "cancelled")
    await delivery.events.emit(event)
    assert bus.outbound.get_nowait().event is event


@pytest.mark.parametrize("phase", ["started", "succeeded", "failed", "cancelled"])
def test_compaction_durability_is_independent_of_subscribers(phase):
    projection = project_notification("chat", ContextCompactionEvent("c1", phase))
    assert projection is not None
    assert projection.deliver_offline
    assert projection.attach_turn_metadata
    assert projection.persistence == ("transient" if phase == "started" else "turn_activity")
