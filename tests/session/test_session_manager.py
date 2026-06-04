"""Tests for session management (Session + SessionManager)."""

import json

import pytest

from blackcat.session.manager import Session, SessionManager

# ── Session dataclass ──────────────────────────────────────────────


def test_session_add_message():
    s = Session(key="test:1")
    s.add_message("user", "hello")
    assert len(s.messages) == 1
    assert s.messages[0]["role"] == "user"
    assert s.messages[0]["content"] == "hello"
    assert "timestamp" in s.messages[0]


def test_session_add_message_with_kwargs():
    s = Session(key="test:1")
    s.add_message("assistant", "hi", tool_calls=[{"id": "t1"}])
    assert s.messages[0]["tool_calls"] == [{"id": "t1"}]


def test_session_get_history_respects_max():
    s = Session(key="test:1")
    for i in range(20):
        s.add_message("user", f"msg {i}")
    history = s.get_history(max_messages=5)
    assert len(history) == 5
    # Should be the 5 most recent
    assert history[0]["content"] == "msg 15"
    assert history[-1]["content"] == "msg 19"


def test_session_get_history_preserves_tool_metadata():
    s = Session(key="test:1")
    s.add_message("user", "question")
    s.add_message("assistant", "thinking", tool_calls=[{"id": "c1"}])
    s.add_message("tool", "result", tool_call_id="c1", name="shell")
    history = s.get_history()
    # Tool metadata is preserved in history
    assert len(history) == 3
    assert history[1]["tool_calls"] == [{"id": "c1"}]
    assert history[2]["tool_call_id"] == "c1"
    assert history[2]["name"] == "shell"


def test_session_clear():
    s = Session(key="test:1")
    s.add_message("user", "hello")
    s.clear()
    assert s.messages == []


# ── SessionManager persistence ─────────────────────────────────────


@pytest.fixture
def session_mgr(tmp_path, monkeypatch):
    """SessionManager using a temp directory for sessions."""
    mgr = SessionManager(workspace=tmp_path)
    # Override sessions_dir to use tmp
    mgr.sessions_dir = tmp_path / "sessions"
    mgr.sessions_dir.mkdir(exist_ok=True)
    return mgr


def test_get_or_create_new(session_mgr):
    s = session_mgr.get_or_create("telegram:12345")
    assert s.key == "telegram:12345"
    assert s.messages == []


def test_get_or_create_cached(session_mgr):
    s1 = session_mgr.get_or_create("t:1")
    s1.add_message("user", "hi")
    s2 = session_mgr.get_or_create("t:1")
    assert s2 is s1  # Same object from cache


def test_save_and_load(session_mgr):
    s = session_mgr.get_or_create("telegram:42")
    s.add_message("user", "hello")
    s.add_message("assistant", "hi there")
    session_mgr.save(s)

    # Clear cache and reload
    session_mgr._cache.clear()
    loaded = session_mgr.get_or_create("telegram:42")
    assert len(loaded.messages) == 2
    assert loaded.messages[0]["role"] == "user"
    assert loaded.messages[1]["content"] == "hi there"


def test_save_stores_key_in_metadata(session_mgr):
    s = session_mgr.get_or_create("discord:abc")
    session_mgr.save(s)

    path = session_mgr._get_session_path("discord:abc")
    with open(path) as f:
        first = json.loads(f.readline())
    assert first["_type"] == "metadata"
    assert first["key"] == "discord:abc"


def test_save_uses_utf8(session_mgr):
    s = session_mgr.get_or_create("test:utf8")
    s.add_message("user", "cafe latte")
    session_mgr.save(s)

    path = session_mgr._get_session_path("test:utf8")
    raw = path.read_text(encoding="utf-8")
    assert "cafe latte" in raw


def test_invalidate(session_mgr):
    s = session_mgr.get_or_create("t:1")
    session_mgr.save(s)
    session_mgr.invalidate("t:1")
    assert "t:1" not in session_mgr._cache


def test_delete(session_mgr):
    s = session_mgr.get_or_create("t:del")
    session_mgr.save(s)
    assert session_mgr.delete_session("t:del") is True
    assert session_mgr.delete_session("t:del") is False  # Already deleted


def test_delete_nonexistent(session_mgr):
    assert session_mgr.delete_session("nope:nope") is False


def test_list_sessions(session_mgr):
    for key in ["telegram:1", "discord:2", "cli:local"]:
        s = session_mgr.get_or_create(key)
        s.add_message("user", "hi")
        session_mgr.save(s)

    sessions = session_mgr.list_sessions()
    keys = {s["key"] for s in sessions}
    assert "telegram:1" in keys
    assert "discord:2" in keys
    assert "cli:local" in keys


def test_list_sessions_uses_stored_key(session_mgr):
    s = session_mgr.get_or_create("telegram:special_chat")
    session_mgr.save(s)
    sessions = session_mgr.list_sessions()
    assert any(s["key"] == "telegram:special_chat" for s in sessions)


def test_load_corrupted_file(session_mgr):
    """Corrupted JSONL should not crash, just return None."""
    path = session_mgr._get_session_path("bad:session")
    path.write_text("not valid json\n", encoding="utf-8")
    session_mgr._cache.clear()
    s = session_mgr.get_or_create("bad:session")
    # Should create a fresh session instead of crashing
    assert s.key == "bad:session"
    assert s.messages == []


# ── Compaction filtering ──────────────────────────────────────────
# Filtering happens in get_history (read boundary), not _load.
# session.messages retains the full archive; get_history returns the working set.


def test_load_preserves_full_archive(session_mgr):
    """Loading should return ALL messages — full archive stays intact."""
    s = session_mgr.get_or_create("t:archive")
    s.add_message("user", "old message")
    s.add_message("assistant", "old reply")
    s.add_message("system", "Summary of old conversation")
    s.add_message("user", "new message")
    session_mgr.save(s)

    session_mgr._cache.clear()
    loaded = session_mgr.get_or_create("t:archive")

    # Full archive preserved
    assert len(loaded.messages) == 4
    assert loaded.messages[0]["content"] == "old message"


def test_get_history_filters_from_last_compaction():
    """get_history uses last_consolidated to filter messages."""
    s = Session(key="t:compact")
    s.add_message("user", "old message 1")
    s.add_message("assistant", "old reply 1")
    s.add_message("user", "old message 2")
    s.add_message("assistant", "old reply 2")
    s.add_message("system", "Summary: user discussed topics 1 and 2")
    s.last_consolidated = 4  # Mark first 4 messages as consolidated
    s.add_message("user", "new message")
    s.add_message("assistant", "new reply")

    history = s.get_history(max_messages=50)

    # Should filter from last_consolidated, then skip to first user message
    # Summary at front gets dropped because get_history starts from user message
    assert len(history) == 2
    assert history[0]["content"] == "new message"
    assert history[1]["content"] == "new reply"


def test_get_history_filters_from_latest_compaction():
    """Multiple compactions: last_consolidated points to most recent."""
    s = Session(key="t:multi")
    s.add_message("user", "ancient message")
    s.add_message("system", "First compaction summary")
    s.add_message("user", "old message")
    s.add_message("assistant", "old reply")
    s.add_message("system", "Second compaction summary")
    s.last_consolidated = 4  # Mark first 4 messages as consolidated
    s.add_message("user", "latest message")

    history = s.get_history(max_messages=50)

    # get_history starts from first user message, so summary is dropped
    assert len(history) == 1
    assert history[0]["content"] == "latest message"


def test_get_history_no_compaction_returns_all():
    """Session without compaction should return all messages unchanged."""
    s = Session(key="t:nocompact")
    s.add_message("user", "msg 1")
    s.add_message("assistant", "reply 1")
    s.add_message("user", "msg 2")

    history = s.get_history(max_messages=50)

    assert len(history) == 3
    assert history[0]["content"] == "msg 1"


def test_get_history_compaction_only_returns_summary():
    """If only compaction summary remains, get_history now preserves it."""
    s = Session(key="t:justcompact")
    s.add_message("user", "old stuff")
    s.add_message("assistant", "old reply")
    s.add_message("system", "Summary of everything")
    s.last_consolidated = 2  # Mark first 2 messages as consolidated

    history = s.get_history(max_messages=50)

    # get_history now preserves the system summary message
    assert len(history) == 1
    assert history[0]["role"] == "system"
    assert history[0]["content"] == "Summary of everything"


def test_get_history_filtered_then_capped():
    """get_history filters from last_consolidated, then applies max_messages cap."""
    s = Session(key="t:histcount")
    # 20 old messages
    for i in range(20):
        s.add_message("user", f"old {i}")
    # Compaction summary
    s.add_message("system", "Summary of 20 messages")
    s.last_consolidated = 20  # Mark first 20 messages as consolidated
    # 3 new messages
    s.add_message("user", "new 1")
    s.add_message("assistant", "reply 1")
    s.add_message("user", "new 2")

    # Full archive intact
    assert len(s.messages) == 24

    # get_history returns from first user message after consolidation: 3 new messages
    history = s.get_history(max_messages=50)
    assert len(history) == 3
    assert history[0]["content"] == "new 1"

    # max_messages cap works on filtered set, then aligns to user message
    # With max=2: [reply 1, new 2] -> aligns to user -> [new 2]
    history_capped = s.get_history(max_messages=2)
    assert len(history_capped) == 1
    assert history_capped[0]["content"] == "new 2"


def test_save_after_compaction_preserves_full_archive(session_mgr):
    """Save after compaction should write the full archive, not just the filtered view."""
    s = session_mgr.get_or_create("t:savefull")
    s.add_message("user", "old message")
    s.add_message("assistant", "old reply")
    s.add_message("system", "Summary")
    s.last_consolidated = 2  # Mark first 2 messages as consolidated
    s.add_message("user", "new message")
    session_mgr.save(s)

    # Reload from disk — full archive should be there
    session_mgr._cache.clear()
    loaded = session_mgr.get_or_create("t:savefull")
    assert len(loaded.messages) == 4

    # get_history starts from first user message after consolidation
    history = loaded.get_history(max_messages=50)
    assert len(history) == 1
    assert history[0]["content"] == "new message"
