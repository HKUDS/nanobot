"""Tests for internal turn continuation policy."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from blackcat.bus.events import InboundMessage
from blackcat.session.goal_state import GOAL_STATE_KEY
from blackcat.session.turn_continuation import (
    INTERNAL_CONTINUATION_KIND_META,
    INTERNAL_CONTINUATION_META,
    INTERNAL_CONTINUATION_PENDING_META,
    INTERNAL_CONTINUATION_RUN_STARTED_AT_META,
    internal_continuation_pending,
    internal_continuation_run_started_at,
    maybe_continue_turn,
    should_finalize_on_max_iterations,
    should_stream_budget_response,
)


@pytest.mark.asyncio
async def test_maybe_continue_turn_queues_internal_message():
    meta = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "Finish the migration.",
            "ui_summary": "migration",
        },
    }
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": "paused"},
    ]
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
    ctx = SimpleNamespace(
        session=SimpleNamespace(metadata=meta),
        msg=InboundMessage(
            channel="feishu",
            sender_id="u1",
            chat_id="c1",
            content="start",
            metadata={
                "message_id": "msg-1",
                "origin_message_id": "msg-0",
                "_wants_stream": True,
                "_stream_id": "stream-1",
                "_stream_delta": True,
                "_stream_end": True,
                "_resuming": True,
                "webui": True,
            },
        ),
        session_key="feishu:c1",
        pending_queue=pending,
        stop_reason="max_iterations",
        final_content="paused",
        all_messages=messages,
        suppress_response=False,
        visible_run_started_at=1234.5,
    )

    assert await maybe_continue_turn(ctx) is True

    queued = pending.get_nowait()
    assert queued.sender_id == "system:continuation"
    assert queued.metadata[INTERNAL_CONTINUATION_META] is True
    assert queued.metadata[INTERNAL_CONTINUATION_KIND_META] == "sustained_goal"
    assert queued.metadata[INTERNAL_CONTINUATION_RUN_STARTED_AT_META] == 1234.5
    assert internal_continuation_run_started_at(queued.metadata) == 1234.5
    assert internal_continuation_pending(ctx.msg.metadata)
    assert queued.metadata["webui"] is True
    assert queued.metadata["message_id"] == "msg-1"
    assert queued.metadata["origin_message_id"] == "msg-0"
    assert queued.metadata["_wants_stream"] is True
    assert "_stream_id" not in queued.metadata
    assert "_stream_delta" not in queued.metadata
    assert "_stream_end" not in queued.metadata
    assert "_resuming" not in queued.metadata
    assert "Finish the migration." in queued.content
    assert ctx.all_messages == messages[:-1]
    assert ctx.final_content == ""
    assert ctx.suppress_response is True
    assert ctx.msg.metadata[INTERNAL_CONTINUATION_PENDING_META] is True
    assert meta["_sustained_goal_continuation_rounds"] == 1


@pytest.mark.asyncio
async def test_internal_continuation_respects_round_limit():
    meta = {
        GOAL_STATE_KEY: {"status": "active", "objective": "x"},
        "_sustained_goal_continuation_rounds": 12,
    }
    ctx = SimpleNamespace(
        session=SimpleNamespace(metadata=meta),
        msg=InboundMessage(channel="feishu", sender_id="u1", chat_id="c1", content="start"),
        session_key="feishu:c1",
        pending_queue=asyncio.Queue(),
        stop_reason="max_iterations",
        final_content="paused",
        all_messages=[],
    )

    assert should_stream_budget_response(
        stop_reason="max_iterations",
        pending_queue_available=True,
        session_metadata=meta,
    )
    assert await maybe_continue_turn(ctx) is False


def test_internal_continuation_requires_budget_boundary_and_queue():
    meta = {GOAL_STATE_KEY: {"status": "active", "objective": "x"}}

    assert should_stream_budget_response(
        stop_reason="completed",
        pending_queue_available=True,
        session_metadata=meta,
    )
    assert should_stream_budget_response(
        stop_reason="max_iterations",
        pending_queue_available=False,
        session_metadata=meta,
    )
    assert not should_finalize_on_max_iterations(
        pending_queue_available=True,
        session_metadata=meta,
    )
    assert should_finalize_on_max_iterations(
        pending_queue_available=False,
        session_metadata=meta,
    )
    assert should_finalize_on_max_iterations(
        pending_queue_available=True,
        session_metadata={},
    )
