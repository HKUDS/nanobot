from __future__ import annotations

import pytest

from nanobot.bus.outbound_events import (
    ContextCompactionEvent,
    RecoveryStateEvent,
    RetryStatusEvent,
    TurnEndEvent,
)
from nanobot.providers.base import LLMUsage
from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY
from nanobot.webui.outbound_wire import (
    encode_context_compaction,
    encode_recovery_state,
    encode_retry_status,
    encode_turn_end,
)


def test_encode_context_compaction_projects_the_lifecycle() -> None:
    payload = encode_context_compaction(
        "chat-1",
        ContextCompactionEvent(
            compaction_id="compact-1",
            phase="succeeded",
        ),
    )

    assert payload == {
        "event": "context_compaction",
        "chat_id": "chat-1",
        "compaction_id": "compact-1",
        "phase": "succeeded",
    }


def test_encode_recovery_state_omits_absent_optional_fields() -> None:
    payload = encode_recovery_state(
        "chat-1",
        RecoveryStateEvent(
            status="running",
            recovery_id="recovery-1",
            reason="",
            attempts=0,
        ),
    )

    assert payload == {
        "event": "recovery_state",
        "chat_id": "chat-1",
        "status": "running",
        "recovery_id": "recovery-1",
        "attempts": 0,
    }


def test_encode_recovery_state_preserves_false_can_continue() -> None:
    payload = encode_recovery_state(
        "chat-1",
        RecoveryStateEvent(
            status="awaiting_user",
            recovery_id="recovery-1",
            reason="tool_state_unknown",
            attempts=1,
            can_continue=False,
        ),
    )

    assert payload == {
        "event": "recovery_state",
        "chat_id": "chat-1",
        "status": "awaiting_user",
        "recovery_id": "recovery-1",
        "attempts": 1,
        "reason": "tool_state_unknown",
        "can_continue": False,
    }


def test_encode_retry_status_projects_relative_wait_and_turn_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.outbound_wire.time.time", lambda: 120.0)

    payload = encode_retry_status(
        "chat-1",
        RetryStatusEvent(
            state="waiting",
            attempt=2,
            max_attempts=4,
            error_kind="connection",
            next_retry_at=123.5,
        ),
        {WEBUI_TURN_METADATA_KEY: "turn-1", "private": "must-not-leak"},
    )

    assert payload == {
        "event": "retry_status",
        "chat_id": "chat-1",
        "turn_id": "turn-1",
        "state": "waiting",
        "attempt": 2,
        "max_attempts": 4,
        "error_kind": "connection",
        "retry_after_s": 3.5,
    }


def test_encode_turn_end_omits_absent_fields_and_private_metadata() -> None:
    payload = encode_turn_end(
        "chat-1",
        TurnEndEvent(),
        {WEBUI_TURN_METADATA_KEY: 42, "private": "must-not-leak"},
    )

    assert payload == {"event": "turn_end", "chat_id": "chat-1"}


def test_encode_turn_end_projects_complete_wire_contract() -> None:
    usage = LLMUsage.reported(
        input_tokens=80,
        output_tokens=20,
        cache_read_tokens=40,
    ).with_timing(generation_ms=500, ttft_ms=125)
    goal_state = {"active": True, "ui_summary": "Explore codebase"}

    payload = encode_turn_end(
        "chat-1",
        TurnEndEvent(
            latency_ms=1500,
            goal_state=goal_state,
            usage=usage,
            round_usages=(usage,),
            context_window_tokens=128_000,
            outcome="error",
            failure_kind="provider",
            failure_error_kind="connection",
            failure_attempts=4,
            failure_message="Connection refused",
        ),
        {WEBUI_TURN_METADATA_KEY: "turn-1", "private": "must-not-leak"},
    )

    assert payload == {
        "event": "turn_end",
        "chat_id": "chat-1",
        "turn_id": "turn-1",
        "latency_ms": 1500,
        "goal_state": goal_state,
        "usage": usage.to_turn_dict(),
        "round_usages": [usage.to_turn_dict()],
        "context_window_tokens": 128_000,
        "outcome": "error",
        "failure_kind": "provider",
        "failure_error_kind": "connection",
        "failure_attempts": 4,
        "failure_message": "Connection refused",
    }
