"""Tests for Consolidator token estimation skip logic."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.memory import Consolidator


def _make_consolidator(tmp_path, context_window=65536, max_completion=8192):
    provider = MagicMock()
    store = MagicMock()
    store.workspace = tmp_path
    store._cursor_file = tmp_path / "memory" / ".cursor"
    (tmp_path / "memory").mkdir(exist_ok=True)
    store.history_file = tmp_path / "memory" / "history.jsonl"
    sessions = MagicMock()
    c = Consolidator(
        store=store,
        provider=provider,
        model="test",
        sessions=sessions,
        context_window_tokens=context_window,
        max_completion_tokens=max_completion,
        build_messages=MagicMock(return_value=[]),
        get_tool_definitions=MagicMock(return_value=[]),
    )
    return c


def _make_session(key="test:1", msg_count=1):
    session = MagicMock()
    session.key = key
    session.messages = [{"role": "user", "content": "hi"}] * msg_count
    session.last_consolidated = 0
    return session


def test_skip_when_under_budget(tmp_path):
    c = _make_consolidator(tmp_path)
    session = _make_session()
    c._record_estimation(session, 5000)
    assert c._should_skip_estimation(session) is True


def test_no_skip_without_prior_estimate(tmp_path):
    c = _make_consolidator(tmp_path)
    session = _make_session()
    assert c._should_skip_estimation(session) is False


def test_no_skip_when_messages_changed(tmp_path):
    c = _make_consolidator(tmp_path)
    session = _make_session(msg_count=1)
    c._record_estimation(session, 5000)
    session.messages.append({"role": "assistant", "content": "hello"})
    assert c._should_skip_estimation(session) is False


def test_no_skip_when_over_half_budget(tmp_path):
    c = _make_consolidator(tmp_path, context_window=10000, max_completion=2000)
    session = _make_session()
    budget = 10000 - 2000 - c._SAFETY_BUFFER
    c._record_estimation(session, int(budget * 0.6))
    assert c._should_skip_estimation(session) is False


def test_no_skip_when_cursor_changed(tmp_path):
    c = _make_consolidator(tmp_path)
    session = _make_session()
    c._record_estimation(session, 5000)
    # Change cursor
    c.store._cursor_file.write_text("99")
    assert c._should_skip_estimation(session) is False


def test_no_skip_when_workspace_file_changed(tmp_path):
    c = _make_consolidator(tmp_path)
    session = _make_session()
    c._record_estimation(session, 5000)
    # Create a workspace file that changes mtime sum
    (tmp_path / "SOUL.md").write_text("new soul content")
    assert c._should_skip_estimation(session) is False


def test_no_skip_when_last_consolidated_changed(tmp_path):
    c = _make_consolidator(tmp_path)
    session = _make_session()
    c._record_estimation(session, 5000)
    session.last_consolidated = 5
    assert c._should_skip_estimation(session) is False


def test_record_and_skip_roundtrip(tmp_path):
    """Record estimation, then verify skip works and re-record after changes."""
    c = _make_consolidator(tmp_path)
    session = _make_session(msg_count=3)
    c._record_estimation(session, 1000)
    assert c._should_skip_estimation(session) is True

    # After adding a message, skip should fail
    session.messages.append({"role": "user", "content": "more"})
    assert c._should_skip_estimation(session) is False

    # Re-record with new state, skip should work again
    c._record_estimation(session, 1200)
    assert c._should_skip_estimation(session) is True
