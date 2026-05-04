"""Tests for the hallucinated tool call guard."""

from __future__ import annotations

import pytest

from nanobot.agent.guards.hallucinated_tool_call import (
    HallucinatedToolCallGuard,
    HallucinatedToolCallGuardConfig,
)
from nanobot.agent.hook import AgentHookContext
from nanobot.providers.base import ToolCallRequest


def _ctx(
    tool_calls: list[ToolCallRequest] | None = None,
    iteration: int = 0,
) -> AgentHookContext:
    return AgentHookContext(
        iteration=iteration,
        messages=[],
        tool_calls=list(tool_calls or []),
    )


def _tc(name: str, arguments: dict | None = None) -> ToolCallRequest:
    return ToolCallRequest(id=f"tc-{name}", name=name, arguments=arguments or {})


# ---------------------------------------------------------------------------
# Disabled by default — no-op behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_by_default_passes_content_through() -> None:
    guard = HallucinatedToolCallGuard()
    ctx = _ctx()
    # Even an obvious hallucination is left alone when disabled.
    out = guard.finalize_content(ctx, "Done. I'll remind you Monday at 9 AM.")
    assert out == "Done. I'll remind you Monday at 9 AM."


@pytest.mark.asyncio
async def test_disabled_does_not_record_tool_calls() -> None:
    guard = HallucinatedToolCallGuard()
    await guard.before_execute_tools(_ctx(tool_calls=[_tc("cron")]))
    assert guard._tool_names_seen == []


# ---------------------------------------------------------------------------
# Enabled, log-only mode (default annotate_response=False)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enabled_log_only_returns_content_unchanged_on_hallucination(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guard = HallucinatedToolCallGuard(HallucinatedToolCallGuardConfig(enabled=True))
    ctx = _ctx()
    out = guard.finalize_content(ctx, "Done. I'll remind you Monday at 9 AM.")
    assert out == "Done. I'll remind you Monday at 9 AM."
    # Logged but content unchanged — log-only mode is for diagnostics.


@pytest.mark.asyncio
async def test_enabled_no_action_claim_passes_through() -> None:
    guard = HallucinatedToolCallGuard(HallucinatedToolCallGuardConfig(enabled=True))
    ctx = _ctx()
    # Pure conversational reply with no action claim.
    msg = "That's a great idea! Let me know how it goes."
    assert guard.finalize_content(ctx, msg) == msg


@pytest.mark.asyncio
async def test_enabled_with_backing_tool_passes_through() -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(enabled=True, annotate_response=True)
    )
    # Tool was called this turn — claim is backed.
    await guard.before_execute_tools(_ctx(tool_calls=[_tc("cron")]))
    msg = "Done. I'll remind you Monday at 9 AM."
    out = guard.finalize_content(_ctx(), msg)
    assert out == msg  # No annotation appended when backing tool was called.


# ---------------------------------------------------------------------------
# Enabled, annotate_response=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_annotate_appends_warning_on_hallucination() -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(enabled=True, annotate_response=True)
    )
    ctx = _ctx()
    msg = "Done. I'll remind you Monday at 9 AM."
    out = guard.finalize_content(ctx, msg)
    assert out is not None
    assert out.startswith(msg)
    assert "verify" in out  # default warning_text mentions verify


@pytest.mark.asyncio
async def test_annotate_with_custom_warning_text() -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(
            enabled=True,
            annotate_response=True,
            warning_text="\n[guard: tool not actually called]",
        )
    )
    out = guard.finalize_content(_ctx(), "I've added it to your calendar.")
    assert out is not None
    assert out.endswith("[guard: tool not actually called]")


# ---------------------------------------------------------------------------
# Backing-tool detection — tool name fragment matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name",
    [
        "cron",
        "mcp_google_calendar_create_event",
        "send_email",
        "gmail_send_email",
        "write_file",
        "drive_create_file",
    ],
)
@pytest.mark.asyncio
async def test_known_backing_tools_suppress_warning(tool_name: str) -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(enabled=True, annotate_response=True)
    )
    await guard.before_execute_tools(_ctx(tool_calls=[_tc(tool_name)]))
    out = guard.finalize_content(_ctx(), "Done. I've sent the email.")
    assert out == "Done. I've sent the email."


@pytest.mark.asyncio
async def test_unrelated_tool_does_not_count_as_backing() -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(enabled=True, annotate_response=True)
    )
    # `read_file` is not on the backing-tools list — it's a read, not a write.
    await guard.before_execute_tools(_ctx(tool_calls=[_tc("read_file")]))
    out = guard.finalize_content(_ctx(), "Done. I've sent the email.")
    assert out is not None
    assert "verify" in out


# ---------------------------------------------------------------------------
# Action claim detection coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "Done. I'll remind you Monday at 9 AM.",
        "I've set a reminder for tomorrow.",
        "Got it. I've added the meeting to your calendar.",
        "Reminder is set for Monday.",
        "I've sent the email to your colleague.",
        "I've saved the file to your drive.",
        "Fixed. I'll alert you when it arrives.",
    ],
)
@pytest.mark.asyncio
async def test_detects_common_action_claims(claim: str) -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(enabled=True, annotate_response=True)
    )
    out = guard.finalize_content(_ctx(), claim)
    assert out is not None
    assert "verify" in out, f"Expected hallucination flag for: {claim!r}"


@pytest.mark.parametrize(
    "non_claim",
    [
        "That's a great idea — what time works best?",
        "Here's what I see in your calendar this week: nothing scheduled.",
        "I'd recommend checking your bank app first.",
        "Sounds good. Let me know if anything changes.",
        "",  # empty content
    ],
)
@pytest.mark.asyncio
async def test_does_not_flag_non_action_responses(non_claim: str) -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(enabled=True, annotate_response=True)
    )
    out = guard.finalize_content(_ctx(), non_claim)
    assert out == non_claim


# ---------------------------------------------------------------------------
# reset() behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_clears_observed_tool_calls() -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(enabled=True, annotate_response=True)
    )
    # Turn 1: cron tool called, then claim — passes through.
    await guard.before_execute_tools(_ctx(tool_calls=[_tc("cron")]))
    out1 = guard.finalize_content(_ctx(), "Done. I'll remind you Monday.")
    assert out1 == "Done. I'll remind you Monday."

    # Turn 2 starts: reset wipes prior tool memory.
    guard.reset()
    out2 = guard.finalize_content(_ctx(), "Done. I'll remind you Monday.")
    assert out2 is not None
    assert "verify" in out2  # No backing tool this turn → flagged.


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_content_returns_none() -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(enabled=True, annotate_response=True)
    )
    assert guard.finalize_content(_ctx(), None) is None


@pytest.mark.asyncio
async def test_custom_pattern_list_overrides_defaults() -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(
            enabled=True,
            annotate_response=True,
            action_claim_patterns=(r"\bbanana\b",),
        )
    )
    # Default patterns (e.g. "I've sent...") are no longer in effect.
    out_default_phrase = guard.finalize_content(_ctx(), "I've sent the email.")
    assert out_default_phrase == "I've sent the email."
    # Custom pattern still triggers.
    out_custom = guard.finalize_content(_ctx(), "I have a banana for you.")
    assert out_custom is not None
    assert "verify" in out_custom


@pytest.mark.asyncio
async def test_custom_backing_tool_fragments() -> None:
    guard = HallucinatedToolCallGuard(
        HallucinatedToolCallGuardConfig(
            enabled=True,
            annotate_response=True,
            backing_tool_fragments=("custom_action",),
        )
    )
    # Default backing-tool fragments (cron, calendar, etc.) no longer apply.
    await guard.before_execute_tools(_ctx(tool_calls=[_tc("cron")]))
    out = guard.finalize_content(_ctx(), "I've set a reminder for Monday.")
    assert out is not None
    assert "verify" in out  # cron is no longer recognized → flagged.

    guard.reset()
    await guard.before_execute_tools(_ctx(tool_calls=[_tc("custom_action_tool")]))
    out2 = guard.finalize_content(_ctx(), "I've set a reminder for Monday.")
    assert out2 == "I've set a reminder for Monday."
