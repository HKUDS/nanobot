"""IT-15: CanonicalEventBuilder events flow through MessageBus.

Verifies that canonical events can be built, wrapped in OutboundMessage
metadata, and published/consumed through the bus with correct structure
and incrementing sequence numbers.

Does not require LLM API key.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from nanobot.bus.canonical import CanonicalEventBuilder
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_builder() -> CanonicalEventBuilder:
    return CanonicalEventBuilder(
        run_id="run-abc",
        session_id="sess-123",
        turn_id="turn_00001",
        actor_id="main",
    )


def _event_to_outbound(event: dict) -> OutboundMessage:
    """Wrap a canonical event dict in an OutboundMessage for bus transport."""
    return OutboundMessage(
        channel="cli",
        chat_id="test-chat",
        content=json.dumps(event),
        metadata={"event_type": event["type"]},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCanonicalEventStructure:
    def test_run_start_has_required_fields(self) -> None:
        """run_start() returns an event with all envelope fields."""
        builder = _make_builder()
        event = builder.run_start()

        assert event["type"] == "run.start"
        assert event["run_id"] == "run-abc"
        assert event["session_id"] == "sess-123"
        assert event["turn_id"] == "turn_00001"
        assert event["v"] == 1
        assert "ts" in event
        assert "event_id" in event
        assert event["actor"] == {"kind": "agent", "id": "main"}
        assert event["seq"] == 1

    def test_text_delta_has_payload(self) -> None:
        """text_delta() includes text in the payload."""
        builder = _make_builder()
        _ = builder.run_start()  # seq 1
        event = builder.text_delta("hello world")

        assert event["type"] == "message.part"
        assert event["payload"]["part_type"] == "text"
        assert event["payload"]["text"] == "hello world"

    def test_text_flush_has_payload(self) -> None:
        """text_flush() includes full text in the payload."""
        builder = _make_builder()
        event = builder.text_flush("complete response")

        assert event["payload"]["part_type"] == "text_flush"
        assert event["payload"]["text"] == "complete response"


class TestSequenceNumbers:
    def test_sequence_numbers_increment(self) -> None:
        """Each event from the same builder gets an incrementing seq number."""
        builder = _make_builder()

        e1 = builder.run_start()
        e2 = builder.text_delta("chunk1")
        e3 = builder.text_delta("chunk2")
        e4 = builder.text_flush("full text")

        assert e1["seq"] == 1
        assert e2["seq"] == 2
        assert e3["seq"] == 3
        assert e4["seq"] == 4

    def test_independent_builders_have_independent_sequences(self) -> None:
        """Two builders maintain separate sequence counters."""
        b1 = _make_builder()
        b2 = CanonicalEventBuilder(
            run_id="run-other",
            session_id="sess-other",
            turn_id="turn_00002",
            actor_id="web",
        )

        assert b1.run_start()["seq"] == 1
        assert b1.text_delta("a")["seq"] == 2
        assert b2.run_start()["seq"] == 1
        assert b2.text_delta("b")["seq"] == 2


class TestEventsPublishableToBus:
    async def test_event_roundtrips_through_bus(self) -> None:
        """A canonical event wrapped in OutboundMessage survives bus publish/consume."""
        bus = MessageBus()
        builder = _make_builder()
        event = builder.run_start()
        msg = _event_to_outbound(event)

        await bus.publish_outbound(msg)
        received = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)

        assert received.channel == "cli"
        assert received.chat_id == "test-chat"
        payload = json.loads(received.content)
        assert payload["type"] == "run.start"
        assert payload["run_id"] == "run-abc"
        assert payload["seq"] == 1

    async def test_multiple_events_preserve_order(self) -> None:
        """Multiple events published to the bus arrive in FIFO order."""
        bus = MessageBus()
        builder = _make_builder()

        events = [
            builder.run_start(),
            builder.text_delta("chunk1"),
            builder.text_delta("chunk2"),
            builder.text_flush("full"),
        ]

        for evt in events:
            await bus.publish_outbound(_event_to_outbound(evt))

        received_seqs: list[int] = []
        for _ in events:
            msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
            payload = json.loads(msg.content)
            received_seqs.append(payload["seq"])

        assert received_seqs == [1, 2, 3, 4]
