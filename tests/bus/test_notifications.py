import asyncio
from dataclasses import dataclass

import pytest

from nanobot.agent.turn_delivery import TurnDeliveryFactory, TurnRoute
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.notification_delivery import NOTIFICATION_AUDIENCES
from nanobot.bus.outbound_events import (
    FileEditEvent,
    ProgressEvent,
    StreamDeltaEvent,
    StreamEndEvent,
)
from nanobot.bus.queue import MessageBus
from nanobot.events import AgentEvent, ContextCompactionEvent, EventSink, RetryWaitEvent
from nanobot.utils.progress_events import output_events
from nanobot.webui.outbound_wire import project_notification


async def test_sink_isolates_observer_failure_but_propagates_cancellation():
    async def broken(event):
        raise ValueError("observer failed")

    await EventSink(broken).emit(AgentEvent())

    async def cancelled(event):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await EventSink(cancelled).emit(AgentEvent())


async def test_scoped_output_preserves_routing_and_stream_segment_ownership():
    bus = MessageBus()
    delivery = TurnDeliveryFactory(bus).create(InboundMessage(
        channel="websocket", sender_id="u", chat_id="chat", content="",
        metadata={"_wants_stream": True, "origin_message_id": "original"},
    ), "websocket:chat", enable_stream=True)
    events = [
        ProgressEvent(content="thinking"),
        FileEditEvent(file_edit_events=[{"phase": "start", "path": "a.py"}]),
        StreamDeltaEvent(content="first"),
        StreamEndEvent(resuming=True, merge_next=True),
        StreamDeltaEvent(content="tail"),
    ]
    for event in events:
        await delivery.events.emit(event)
    await delivery.abort_stream()
    messages = [bus.outbound.get_nowait() for _ in range(6)]
    assert [message.content for message in messages] == ["thinking", "", "first", "", "tail", ""]
    assert all(message.chat_id == "chat" for message in messages)
    assert all(message.metadata["origin_message_id"] == "original" for message in messages)
    streams = [message.event for message in messages[2:]]
    assert all(isinstance(event, StreamDeltaEvent | StreamEndEvent) for event in streams)
    assert len({event.stream_id for event in streams}) == 1
    assert isinstance(streams[-1], StreamEndEvent)
    assert streams[-1].merge_next is False
    await delivery.abort_stream()
    assert bus.outbound.empty()


async def test_output_consumer_capability_survives_callback_adaptation():
    bus = MessageBus()
    quiet = TurnDeliveryFactory(bus, lambda *_: TurnRoute("websocket", "chat")).create(
        InboundMessage(channel="system", sender_id="job", chat_id="websocket:chat", content=""),
        "websocket:chat",
    )
    assert quiet.events.accepts(ContextCompactionEvent)
    assert not quiet.events.accepts(FileEditEvent)

    received = []

    async def text_only(content, *, tool_hint=False):
        received.append(content)

    events = output_events(default=quiet.events, on_progress=text_only)
    assert events.accepts(ProgressEvent)
    assert not events.accepts(FileEditEvent)
    await events.emit(ProgressEvent(content="working"))
    await events.emit(ContextCompactionEvent("compact", "succeeded"))
    assert received == ["working"]
    assert bus.outbound.get_nowait().event == ContextCompactionEvent("compact", "succeeded")


async def test_scope_snapshots_route_and_queues_events_in_order():
    bus = MessageBus()
    metadata = {"slack": {"thread_ts": "original"}}
    factory = TurnDeliveryFactory(bus)
    delivery = factory.create(InboundMessage(
        channel="slack", sender_id="u", chat_id="chat", content="", metadata=metadata,
    ), "unified:default")
    metadata["slack"]["thread_ts"] = "moved"
    for phase in ("started", "succeeded"):
        await delivery.events.emit(ContextCompactionEvent("c1", phase))
    for phase in ("started", "succeeded"):
        message = bus.outbound.get_nowait()
        assert message.metadata == {"slack": {"thread_ts": "original"}}
        assert message.event == ContextCompactionEvent("c1", phase)
    assert bus.outbound.empty()


async def test_new_internal_event_needs_explicit_audience(monkeypatch):
    @dataclass(frozen=True)
    class RetryStatus(AgentEvent):
        state: str = "waiting"
        attempt: int = 1

    bus = MessageBus()
    factory = TurnDeliveryFactory(bus)
    delivery = factory.create(InboundMessage(
        channel="websocket", sender_id="u", chat_id="chat", content="",
    ), "websocket:chat")
    event = RetryStatus()
    await delivery.events.emit(event)
    assert bus.outbound.empty()
    assert project_notification("chat", event) is None

    monkeypatch.setitem(NOTIFICATION_AUDIENCES, RetryStatus, "interactive")
    await delivery.events.emit(event)
    assert bus.outbound.get_nowait().event is event
    # Routing registration alone does not authorize serialization of private fields.
    assert project_notification("chat", event) is None


async def test_background_scope_keeps_retry_quiet_but_delivers_compaction():
    bus = MessageBus()
    factory = TurnDeliveryFactory(bus,
                                  lambda *_: TurnRoute("websocket", "chat"))
    delivery = factory.create(InboundMessage(
        channel="system", sender_id="job", chat_id="websocket:chat", content="",
    ), "websocket:chat")
    await delivery.events.emit(RetryWaitEvent("waiting"))
    assert bus.outbound.empty()
    event = ContextCompactionEvent("c1", "cancelled")
    await delivery.events.emit(event)
    assert bus.outbound.get_nowait().event is event


@pytest.mark.parametrize("channel", ["websocket", "cli", "slack", "custom"])
async def test_bus_routes_arbitrary_events_and_text_through_one_queue(channel):
    @dataclass(frozen=True)
    class JobFinished(AgentEvent):
        job_id: str

    bus = MessageBus()
    text = OutboundMessage(channel=channel, chat_id="chat", content="hello")
    event = JobFinished("job-1")
    await bus.publish_outbound(text)
    await bus.publish_event(event, channel=channel, chat_id="chat", metadata={"thread": "1"})
    assert await bus.consume_outbound() is text
    delivered = await bus.consume_outbound()
    assert (delivered.channel, delivered.chat_id) == (channel, "chat")
    assert delivered.event is event
    assert delivered.content == ""
    assert delivered.metadata == {"thread": "1"}
    assert bus.outbound.empty()


async def test_bus_event_preserves_existing_text_fallback():
    bus = MessageBus()
    event = RetryWaitEvent("waiting")
    await bus.publish_event(event, channel="slack", chat_id="chat")
    delivered = await bus.consume_outbound()
    assert delivered.event is event
    assert delivered.content == "waiting"


@pytest.mark.parametrize("phase", ["started", "succeeded", "failed", "cancelled"])
def test_compaction_durability_is_independent_of_subscribers(phase):
    projection = project_notification("chat", ContextCompactionEvent("c1", phase))
    assert projection is not None
    assert projection.deliver_offline
    assert projection.attach_turn_metadata
    assert projection.persistence == ("transient" if phase == "started" else "turn_activity")
