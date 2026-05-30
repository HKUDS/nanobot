"""Tests for _elide_old_tool_results — per-turn history trimming.

The structural fix for "tool results from earlier turns accumulate in the
LLM context, blowing the per-turn budget". Tool results from turns older
than K user-turns get replaced with a small stub that names the tool and
invites a re-call if the content is needed. The full messages list is
preserved in session history; only the LLM-bound view is trimmed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_loop(keep: int = 3):
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
            keep_recent_turn_tool_results=keep,
        )


def _tool_msg(name: str, content: str, tool_call_id: str = "x") -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": content}


# ---- disabled by default -----------------------------------------------------


def test_disabled_when_keep_negative_one() -> None:
    loop = _make_loop(keep=-1)
    msgs = [
        {"role": "user", "content": "hi"},
        _tool_msg("read_file", "x" * 5000),
        {"role": "user", "content": "again"},
    ]
    out = loop._elide_old_tool_results(msgs)
    assert out == msgs, "negative keep disables elision entirely"


# ---- boundary by k user-turns -----------------------------------------------


def test_recent_tool_results_preserved(keep: int = 3) -> None:
    loop = _make_loop(keep=3)
    big = "x" * 5000
    msgs = [
        {"role": "user", "content": "u1"},
        _tool_msg("read_file", big, "a"),
        {"role": "user", "content": "u2"},
        _tool_msg("read_file", big, "b"),
        {"role": "user", "content": "u3"},
        _tool_msg("read_file", big, "c"),
    ]
    out = loop._elide_old_tool_results(msgs)
    # All within last 3 user-turns → none elided.
    for orig, new in zip(msgs, out):
        assert orig == new


def test_older_results_elided_when_window_exceeded() -> None:
    loop = _make_loop(keep=2)
    big = "x" * 5000
    msgs = [
        {"role": "user", "content": "u1"},
        _tool_msg("read_file", big, "old"),
        {"role": "user", "content": "u2"},
        _tool_msg("read_file", big, "u2-result"),
        {"role": "user", "content": "u3"},
        _tool_msg("read_file", big, "u3-result"),
    ]
    out = loop._elide_old_tool_results(msgs)

    # 'old' is from u1; with keep=2 the boundary is at u2. So 'old' gets elided.
    elided = out[1]
    assert elided["content"].startswith("[Tool result elided")
    assert "read_file" in elided["content"]
    assert "5,000" in elided["content"] or "5000" in elided["content"]

    # u2 and u3 results stay verbatim
    assert out[3]["content"] == big
    assert out[5]["content"] == big


def test_small_results_not_elided() -> None:
    """No point eliding a 50-char string with a 150-char stub."""
    loop = _make_loop(keep=1)
    msgs = [
        {"role": "user", "content": "u1"},
        _tool_msg("read_file", "small result"),
        {"role": "user", "content": "u2"},
        _tool_msg("read_file", "x" * 5000),
    ]
    out = loop._elide_old_tool_results(msgs)
    # 'small result' is older than keep=1 boundary, but below STUB_MIN_CHARS — stays
    assert out[1]["content"] == "small result"


def test_does_not_elide_when_no_old_turns() -> None:
    loop = _make_loop(keep=5)
    big = "x" * 5000
    msgs = [
        {"role": "user", "content": "u1"},
        _tool_msg("read_file", big),
    ]
    out = loop._elide_old_tool_results(msgs)
    assert out[1]["content"] == big, "only 1 user-turn present; nothing to elide"


def test_preserves_non_tool_messages() -> None:
    """User/assistant/system messages must be untouched regardless of age."""
    loop = _make_loop(keep=1)
    big_assistant_text = "x" * 5000
    msgs = [
        {"role": "user", "content": "ancient user message"},
        {"role": "assistant", "content": big_assistant_text},
        _tool_msg("read_file", "y" * 5000),
        {"role": "user", "content": "current user"},
    ]
    out = loop._elide_old_tool_results(msgs)
    # Assistant message in older turn must be preserved verbatim.
    assert out[1]["content"] == big_assistant_text
    # The tool message in the same older turn DOES get elided.
    assert out[2]["content"].startswith("[Tool result elided")


def test_preserves_tool_call_ids_and_names() -> None:
    """The stub replaces only `content`; tool_call_id / name / role stay."""
    loop = _make_loop(keep=0)  # elide everything before the current user turn
    msgs = [
        {"role": "user", "content": "u1"},
        _tool_msg("calendar_list_events", "x" * 5000, tool_call_id="abc123"),
        {"role": "user", "content": "u2"},
    ]
    out = loop._elide_old_tool_results(msgs)
    elided = out[1]
    assert elided["role"] == "tool"
    assert elided["tool_call_id"] == "abc123"
    assert elided["name"] == "calendar_list_events"
    assert "calendar_list_events" in elided["content"]


def test_input_messages_list_unmodified() -> None:
    """Elision must produce a new list; the input (used for session history)
    stays whole."""
    loop = _make_loop(keep=0)
    big = "x" * 5000
    msgs = [
        {"role": "user", "content": "u1"},
        _tool_msg("read_file", big),
        {"role": "user", "content": "u2"},
    ]
    snapshot = [dict(m) for m in msgs]
    _ = loop._elide_old_tool_results(msgs)
    assert msgs == snapshot, "input list must not be mutated"


# ---- schema default ----------------------------------------------------------


def test_schema_default_is_3() -> None:
    from nanobot.config.schema import AgentDefaults
    assert AgentDefaults().keep_recent_turn_tool_results == 3
