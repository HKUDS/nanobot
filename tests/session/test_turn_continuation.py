"""Tests for internal turn continuation policy."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    explicit_goal_requested,
    sustained_goal_turn,
)
from nanobot.session.turn_continuation import (
    INTERNAL_CONTINUATION_KIND_META,
    INTERNAL_CONTINUATION_META,
    INTERNAL_CONTINUATION_PENDING_META,
    INTERNAL_CONTINUATION_RUN_STARTED_AT_META,
    _save_skip_for_turn,
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
                "webui": True,
                "original_command": "/goal",
                "goal_requested": True,
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
    assert not explicit_goal_requested(queued.metadata)
    assert sustained_goal_turn(meta, message_metadata=queued.metadata)
    assert "Finish the migration." in queued.content
    assert ctx.all_messages == messages[:-1]
    assert ctx.final_content == ""
    assert ctx.suppress_response is True
    assert ctx.msg.metadata[INTERNAL_CONTINUATION_PENDING_META] is True
    assert meta["_sustained_goal_continuation_rounds"] == 1


@pytest.mark.asyncio
async def test_maybe_continue_turn_stops_after_failed_goal_completion_attempt():
    # Goal remains active while the run already contains a completion attempt
    # (e.g. a malformed update_goal action=complete call from #4864). Continuing
    # would only re-prompt the model to retry the same failing completion, so an
    # internal continuation must NOT be scheduled.
    meta = {
        GOAL_STATE_KEY: {"status": "active", "objective": "Finish the migration."},
    }
    assistant_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "update_goal",
                    "arguments": '{"action": "complete", "recap": "done"}',
                },
            }
        ],
    }
    tool_msg = {
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "update_goal",
        "content": "Error: action is required",
    }
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "start"},
        assistant_msg,
        tool_msg,
        {"role": "assistant", "content": "paused"},
    ]
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
    ctx = SimpleNamespace(
        session=SimpleNamespace(metadata=meta),
        msg=InboundMessage(channel="feishu", sender_id="u1", chat_id="c1", content="start"),
        session_key="feishu:c1",
        pending_queue=pending,
        stop_reason="max_iterations",
        final_content="paused",
        all_messages=messages,
        suppress_response=False,
        visible_run_started_at=100.0,
    )

    assert await maybe_continue_turn(ctx) is False
    assert pending.empty()


@pytest.mark.asyncio
async def test_maybe_continue_turn_allows_other_goal_work_to_continue():
    # A run whose tool work did not end on a failed completion attempt still
    # qualifies for an internal continuation.
    meta = {
        GOAL_STATE_KEY: {"status": "active", "objective": "Finish the migration."},
    }
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": "working, ran out of budget"},
    ]
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
    ctx = SimpleNamespace(
        session=SimpleNamespace(metadata=meta),
        msg=InboundMessage(channel="feishu", sender_id="u1", chat_id="c1", content="start"),
        session_key="feishu:c1",
        pending_queue=pending,
        stop_reason="max_iterations",
        final_content="working, ran out of budget",
        all_messages=messages,
        suppress_response=False,
        visible_run_started_at=100.0,
    )

    assert await maybe_continue_turn(ctx) is True
    assert not pending.empty()


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


def test_save_skip_matches_prefix_when_current_message_merged():
    skip = _save_skip_for_turn(
        message_metadata=None,
        initial_message_count=2,  # [system, merged user]
        history_count=1,
        input_persisted_early=True,
    )
    assert skip == 2


def test_save_skip_unchanged_for_standalone_current_message():
    # [system, history user, current user] with the current user already saved.
    assert _save_skip_for_turn(
        message_metadata=None,
        initial_message_count=3,
        history_count=1,
        input_persisted_early=True,
    ) == 3
    assert _save_skip_for_turn(
        message_metadata=None,
        initial_message_count=3,
        history_count=1,
        input_persisted_early=False,
    ) == 2
