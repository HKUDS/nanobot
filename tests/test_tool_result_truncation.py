"""Tests for the tool-result truncation layer in AgentLoop._cap_tool_result."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


def _make_loop(max_tool_result_chars: int = 0):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        return AgentLoop(
            bus=bus, provider=provider, workspace=workspace,
            max_tool_result_chars=max_tool_result_chars,
        )


def test_cap_zero_means_unlimited() -> None:
    loop = _make_loop(max_tool_result_chars=0)
    huge = "x" * 1_000_000
    assert loop._cap_tool_result("anything", huge) == huge


def test_cap_passes_through_when_under_limit() -> None:
    loop = _make_loop(max_tool_result_chars=1000)
    body = "x" * 999
    assert loop._cap_tool_result("calendar_list", body) == body


def test_cap_truncates_when_over_limit() -> None:
    loop = _make_loop(max_tool_result_chars=100)
    body = "x" * 500
    out = loop._cap_tool_result("calendar_list", body)

    assert len(out) > 100, "truncation tag should be appended after the cap"
    assert out.startswith("x" * 100), "first `cap` chars should be preserved"
    assert "calendar_list" in out, "tool name should appear in the marker"
    assert "500" in out, "original size should appear in the marker"
    assert "100" in out, "cap size should appear in the marker"
    assert "Truncated" in out


def test_cap_handles_non_string_gracefully() -> None:
    """Belt-and-braces: registry returns str, but the loop must not crash on other types."""
    loop = _make_loop(max_tool_result_chars=10)
    # If a tool ever returns a non-string (shouldn't happen but) — pass through.
    assert loop._cap_tool_result("x", None) is None  # type: ignore[arg-type]
    assert loop._cap_tool_result("x", 42) == 42  # type: ignore[arg-type]


def test_cap_default_from_schema_is_20k() -> None:
    """The schema default should land at 20 000 (changed in this PR)."""
    from nanobot.config.schema import AgentDefaults
    assert AgentDefaults().max_tool_result_chars == 20000
