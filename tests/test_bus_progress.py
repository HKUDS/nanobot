from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)
from nanobot.observability.bus_progress import make_bus_progress


def _make_deps():
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    canonical = MagicMock()
    canonical.text_flush = MagicMock(return_value={"type": "text"})
    canonical.tool_call = MagicMock(return_value={"type": "tool_call"})
    canonical.tool_result = MagicMock(return_value={"type": "tool_result"})
    canonical.delegate_start = MagicMock(return_value={"type": "delegate_start"})
    canonical.delegate_end = MagicMock(return_value={"type": "delegate_end"})
    canonical.status = MagicMock(return_value={"type": "status"})
    base_meta = {"_progress": True, "session_id": "s1"}
    return bus, canonical, base_meta


async def _call(event):
    bus, canonical, base_meta = _make_deps()
    cb = make_bus_progress(
        bus=bus,
        channel="telegram",
        chat_id="c1",
        base_meta=base_meta,
        canonical_builder=canonical,
    )
    await cb(event)
    return bus.publish_outbound.call_args[0][0]


async def test_text_chunk_sets_streaming_and_canonical():
    msg = await _call(TextChunk(content="hello", streaming=True))
    assert msg.metadata["_streaming"] is True
    assert msg.metadata["_canonical"] == {"type": "text"}
    assert msg.content == "hello"


async def test_text_chunk_empty_content_no_canonical():
    msg = await _call(TextChunk(content="", streaming=False))
    assert "_canonical" not in msg.metadata
    assert msg.content == ""


async def test_tool_call_sets_tool_hint_and_canonical():
    msg = await _call(ToolCallEvent(tool_call_id="tc1", tool_name="read_file", args={"path": "/x"}))
    assert msg.metadata["_tool_hint"] is True
    assert msg.metadata["_tool_call"]["toolCallId"] == "tc1"
    assert msg.metadata["_canonical"] == {"type": "tool_call"}
    assert msg.content == ""


async def test_tool_result_sets_result_meta():
    msg = await _call(ToolResultEvent(tool_call_id="tc1", result="ok", tool_name="read_file"))
    assert msg.metadata["_tool_result"]["toolCallId"] == "tc1"
    assert "_tool_hint" not in msg.metadata


async def test_delegate_start_sets_canonical():
    msg = await _call(
        DelegateStartEvent(delegation_id="d1", child_role="research", task_title="Find X")
    )
    assert msg.metadata["_canonical"] == {"type": "delegate_start"}


async def test_delegate_end_sets_canonical():
    msg = await _call(DelegateEndEvent(delegation_id="d1", success=True))
    assert msg.metadata["_canonical"] == {"type": "delegate_end"}


async def test_status_event_sets_canonical():
    msg = await _call(StatusEvent(status_code="thinking", label="Thinking…"))
    assert msg.metadata["_canonical"] == {"type": "status"}


async def test_base_meta_is_shallow_copied():
    """Each event gets its own meta dict — events must not share state."""
    bus, canonical, base_meta = _make_deps()
    cb = make_bus_progress(
        bus=bus,
        channel="telegram",
        chat_id="c1",
        base_meta=base_meta,
        canonical_builder=canonical,
    )
    await cb(TextChunk(content="a", streaming=False))
    await cb(TextChunk(content="b", streaming=False))
    assert bus.publish_outbound.call_count == 2
    first_meta = bus.publish_outbound.call_args_list[0][0][0].metadata
    second_meta = bus.publish_outbound.call_args_list[1][0][0].metadata
    assert first_meta is not second_meta
