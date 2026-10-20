"""Tests for internal turn continuation policy."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from nanobot.agent.tools.context import RequestContext
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import INBOUND_META_EXECUTION_ID, ExecutionAdmission, InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import TurnExecutionChanged
from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    explicit_goal_requested,
    sustained_goal_turn,
)
from nanobot.session.recovery import REQUEST_ORIGIN_METADATA_KEY
from nanobot.session.turn_continuation import (
    INTERNAL_CONTINUATION_KIND_META,
    INTERNAL_CONTINUATION_META,
    INTERNAL_CONTINUATION_PENDING_META,
    INTERNAL_CONTINUATION_RUN_STARTED_AT_META,
    _save_skip_for_turn,
    commit_continuation,
    internal_continuation_pending,
    internal_continuation_run_started_at,
    prepare_continuation,
    should_finalize_on_max_iterations,
    should_stream_budget_response,
    sustained_goal_continuation_inbound,
)


def test_prepare_continuation_returns_unadmitted_intent_without_queuing_or_publishing():
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
                INBOUND_META_EXECUTION_ID: "previous-owner",
            },
            execution_admission=ExecutionAdmission(execution_id="previous-owner"),
        ),
        session_key="feishu:c1",
        request_context=RequestContext(
            channel="feishu", chat_id="c1", message_id="msg-1", turn_id="turn-1",
        ),
        pending_queue=pending,
        stop_reason="max_iterations",
        final_content="paused",
        all_messages=messages,
        suppress_response=False,
        visible_run_started_at=1234.5,
    )

    bus = MessageBus()
    facts = []
    bus.subscribe(facts.append, TurnExecutionChanged)
    ctx.delivery = TurnDeliveryFactory(bus).unrouted(ctx.msg, ctx.session_key)
    continuation = prepare_continuation(ctx, session_metadata=ctx.session.metadata)

    assert continuation is not None
    assert pending.empty()
    assert facts == []
    assert continuation.execution_admission is None
    assert INBOUND_META_EXECUTION_ID not in continuation.metadata
    assert ctx.msg.metadata[INBOUND_META_EXECUTION_ID] == "previous-owner"
    assert ctx.msg.execution_admission.execution_id == "previous-owner"
    assert continuation.sender_id == "system:continuation"
    assert continuation.metadata[INTERNAL_CONTINUATION_META] is True
    assert continuation.metadata[INTERNAL_CONTINUATION_KIND_META] == "sustained_goal"
    assert sustained_goal_continuation_inbound(continuation.metadata) is True
    assert continuation.metadata[INTERNAL_CONTINUATION_RUN_STARTED_AT_META] == 1234.5
    assert internal_continuation_run_started_at(continuation.metadata) == 1234.5
    assert not internal_continuation_pending(ctx.msg.metadata)
    assert ctx.all_messages == messages
    assert ctx.final_content == "paused"
    assert ctx.suppress_response is False
    assert "_sustained_goal_continuation_rounds" not in meta
    assert continuation.metadata["webui"] is True
    assert continuation.metadata["message_id"] == "msg-1"
    assert continuation.metadata[REQUEST_ORIGIN_METADATA_KEY] == {
        "message_id": "msg-1", "turn_id": "turn-1",
    }
    assert REQUEST_ORIGIN_METADATA_KEY not in ctx.msg.metadata
    assert continuation.metadata["origin_message_id"] == "msg-0"
    assert continuation.metadata["_wants_stream"] is True
    assert not explicit_goal_requested(continuation.metadata)
    assert sustained_goal_turn(meta, message_metadata=continuation.metadata)
    assert "Finish the migration." in continuation.content

    commit_continuation(ctx)

    assert ctx.all_messages == messages[:-1]
    assert ctx.final_content == ""
    assert ctx.suppress_response is True
    assert ctx.msg.metadata[INTERNAL_CONTINUATION_PENDING_META] is True
    assert meta["_sustained_goal_continuation_rounds"] == 1


def test_generic_internal_continuation_is_not_a_sustained_goal_continuation() -> None:
    assert sustained_goal_continuation_inbound({INTERNAL_CONTINUATION_META: True}) is False


def test_internal_continuation_respects_round_limit():
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
    assert prepare_continuation(ctx, session_metadata=ctx.session.metadata) is None


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


def test_save_skip_unchanged_for_standalone_current_message():
    # [system, history user, current user] with the current user already saved.
    assert _save_skip_for_turn(
        message_metadata=None,
        initial_message_count=3,
        input_persisted_early=True,
    ) == 3
    assert _save_skip_for_turn(
        message_metadata=None,
        initial_message_count=3,
        input_persisted_early=False,
    ) == 2
