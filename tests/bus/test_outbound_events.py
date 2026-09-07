from __future__ import annotations

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
    ContextCompactionEvent,
    ProgressEvent,
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
    outbound_message_for_event,
    replace_outbound_event,
)


def test_compaction_events_have_readable_channel_fallbacks() -> None:
    for event, expected in [
        (ContextCompactionEvent("1", "started"), "Compressing context…"),
        (ContextCompactionEvent("1", "succeeded"), "Context compacted."),
        (ContextCompactionEvent("1", "failed"), "Unable to compact context."),
        (ContextCompactionEvent("1", "cancelled"), "Context compaction cancelled."),
    ]:
        msg = outbound_message_for_event(channel="cli", chat_id="direct", event=event)
        assert msg.content == expected
        assert msg.event is event


def test_progress_event_lives_on_outbound_message_event_field() -> None:
    tool_events = [{"phase": "start", "name": "read_file"}]
    file_edit_events = [{"phase": "end", "path": "app.py"}]

    msg = outbound_message_for_event(
        channel="websocket",
        chat_id="chat-1",
        event=ProgressEvent(
            content="working",
            tool_hint=True,
            reasoning_delta=True,
            stream_id="r1",
            tool_events=tool_events,
            file_edit_events=file_edit_events,
        ),
        metadata={"origin_message_id": "m1"},
    )

    assert msg.content == "working"
    assert msg.metadata == {"origin_message_id": "m1"}

    event = msg.event
    assert isinstance(event, ProgressEvent)
    assert event.content == "working"
    assert event.tool_hint is True
    assert event.reasoning_delta is True
    assert event.stream_id == "r1"
    assert event.tool_events == tool_events
    assert event.file_edit_events == file_edit_events


def test_normal_outbound_message_has_no_runtime_event() -> None:
    msg = OutboundMessage(channel="websocket", chat_id="chat-1", content="hello")

    assert msg.event is None







def test_replace_outbound_event_keeps_routing_metadata() -> None:
    msg = outbound_message_for_event(
        channel="websocket",
        chat_id="chat-1",
        event=StreamDeltaEvent(content="hello", stream_id="s1"),
        metadata={"message_id": "m1"},
    )

    updated = replace_outbound_event(
        msg,
        StreamEndEvent(stream_id="s1", resuming=True, merge_next=True),
        content="hello world",
    )

    assert updated.content == "hello world"
    assert updated.metadata == {"message_id": "m1"}
    assert isinstance(updated.event, StreamEndEvent)
    assert updated.event.stream_id == "s1"
    assert updated.event.resuming is True
    assert updated.event.merge_next is True


def test_streamed_response_event_keeps_final_content_outside_event_payload() -> None:
    msg = outbound_message_for_event(
        channel="cli",
        chat_id="direct",
        event=StreamedResponseEvent(),
        content="final answer",
    )

    assert msg.content == "final answer"
    assert isinstance(msg.event, StreamedResponseEvent)
