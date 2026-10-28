"""Durable shared reading progress does not consume results the viewer hasn't seen."""

import sqlite3
from contextlib import closing

import pytest

from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.manager import Session, SessionManager
from nanobot.session.sqlite_store import (
    SessionConflictError,
    SqliteSessionStore,
    _create_schema_v1,
    _create_schema_v2,
)
from nanobot.webui.transcript import build_webui_thread_response


def _manager(root):
    return SessionManager(root / "workspace", sessions_root=root / "sessions")


def _turn(number):
    return [
        HistoryFact(HistoryKind.INPUT, {"text": f"question {number}"}, f"turn-{number}"),
        HistoryFact(HistoryKind.ANSWER_SEGMENT, {"text": f"answer {number}"}, f"turn-{number}"),
        HistoryFact(HistoryKind.COMPLETION, {"outcome": "completed"}, f"turn-{number}"),
    ]


async def test_late_read_receipt_preserves_new_result_and_survives_restart(tmp_path):
    sessions = _manager(tmp_path)
    session = await sessions.state.get("websocket:shared")
    first = await sessions.state.append_history(session.key, _turn(1), expected_generation=session.generation)
    second = await sessions.state.append_history(session.key, _turn(2), expected_generation=session.generation)
    assert first == {"generation": session.generation, "latest": 1, "read": 0}
    assert second == {"generation": session.generation, "latest": 2, "read": 0}
    before_model = sessions.read_session_file(session.key)
    before_version = sessions.project_history(session.key, lambda history: history.revision)

    read, changed = await sessions.state.mark_read(session.key, session.generation, 1)
    assert changed and read == {**second, "read": 1}
    assert await sessions.state.mark_read(session.key, session.generation, 1) == (read, False)
    assert await sessions.state.mark_read(session.key, session.generation, 0) == (read, False)
    assert sessions.read_session_file(session.key) == before_model
    assert sessions.project_history(session.key, lambda history: history.revision) == before_version
    assert sessions.list_session_metadata()[0]["read_state"] == read
    await sessions.state.aclose()

    reopened = _manager(tmp_path)
    assert reopened.project_history(session.key, lambda history: history.read_state) == read
    assert await reopened.state.mark_read(session.key, session.generation, 2) == ({**read, "read": 2}, True)
    await reopened.state.aclose()


async def test_reset_rejects_old_receipt_and_future_cursor_without_resurrecting_session(tmp_path):
    sessions = _manager(tmp_path)
    old = await sessions.state.get("websocket:reset")
    await sessions.state.append_history(old.key, _turn(1), expected_generation=old.generation)
    await sessions.state.reset(old.key)
    current = await sessions.state.get(old.key)
    with pytest.raises(SessionConflictError):
        await sessions.state.mark_read(old.key, old.generation, 1)
    with pytest.raises(ValueError, match="beyond"):
        await sessions.state.mark_read(current.key, current.generation, 1)
    await sessions.state.delete(current.key)
    with pytest.raises(SessionConflictError):
        await sessions.state.mark_read(current.key, current.generation, 0)
    assert sessions.list_session_metadata() == []
    await sessions.state.aclose()


async def test_progress_and_metadata_only_completion_do_not_create_new_unread_result(tmp_path):
    sessions = _manager(tmp_path)
    session = await sessions.state.get("websocket:progress")
    await sessions.state.append_history(session.key, _turn(1), expected_generation=session.generation)
    state, _ = await sessions.state.mark_read(session.key, session.generation, 1)
    await sessions.state.append_history(
        session.key, [HistoryFact(HistoryKind.PROGRESS, {"text": "working"})], expected_generation=session.generation,
    )
    await sessions.state.append_history(
        session.key, [HistoryFact(HistoryKind.COMPLETION)], expected_generation=session.generation,
        notify_completion=False,
    )
    assert sessions.project_history(session.key, lambda history: history.read_state) == state
    await sessions.state.aclose()


async def test_history_page_acknowledges_its_own_completed_results_not_latest_head(tmp_path):
    sessions = _manager(tmp_path)
    session = await sessions.state.get("websocket:paged")
    await sessions.state.append_history(session.key, [*_turn(1), *_turn(2), *_turn(3)], expected_generation=session.generation)
    latest = sessions.project_history(session.key, lambda history: build_webui_thread_response(session.key, history=history, limit=1))
    older = sessions.project_history(session.key, lambda history: build_webui_thread_response(
        session.key, history=history, limit=1, before=latest["page"]["before_cursor"],
    ))
    assert latest["read_cursor"] == 3
    assert older["read_state"]["latest"] == 3
    assert older["read_cursor"] == 2
    state, _ = await sessions.state.mark_read(session.key, session.generation, older["read_cursor"])
    assert state["latest"] > state["read"]
    await sessions.state.aclose()


def test_v2_upgrade_baselines_existing_history_then_new_results_are_unread(tmp_path):
    store = SqliteSessionStore(tmp_path)
    session = Session(key="websocket:upgrade")
    with closing(sqlite3.connect(store.path)) as db:
        _create_schema_v1(db)
        _create_schema_v2(db)
        db.execute("PRAGMA user_version=2")
        db.execute("INSERT INTO storage_meta VALUES ('jsonl_import', 'complete')")
        db.commit()
    store.save(session)
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("INSERT INTO history_heads (session_key) VALUES (?)", (session.key,))
        db.execute("INSERT INTO history_turns VALUES (?, 0, 1, 0, 0, 1)", (session.key,))
        db.execute("INSERT INTO history_entries VALUES (?, 0, 0, 'completion', ?)", (session.key, _turn(1)[-1].encode()))
        db.commit()
    store.initialize(tmp_path / "workspace")
    assert store.project_history(session.key, lambda history: history.read_state) == {
        "generation": session.generation, "latest": 1, "read": 1,
    }
    assert store.append_history(session.key, _turn(2), expected_generation=session.generation) == {
        "generation": session.generation, "latest": 2, "read": 1,
    }
    store.initialize(tmp_path / "workspace")
    assert store.project_history(session.key, lambda history: history.read_state)["read"] == 1


async def test_forked_history_is_a_read_baseline_without_consuming_source_results(tmp_path):
    sessions = _manager(tmp_path)
    source = await sessions.state.get("websocket:source")
    for number in (1, 2):
        source.add_message("user", f"question {number}")
        source.add_message("assistant", f"answer {number}")
    await sessions.state.finish_turn(source)
    await sessions.state.append_history(source.key, [*_turn(1), *_turn(2)], expected_generation=source.generation)
    target = await sessions.state.fork(source.key, "websocket:fork", 1)
    assert target is not None
    copied = sessions.project_history(target.key, lambda history: history.read_state)
    assert copied == {"generation": target.generation, "latest": 1, "read": 1}
    assert sessions.project_history(source.key, lambda history: history.read_state) == {
        "generation": source.generation, "latest": 2, "read": 0,
    }
    await sessions.state.aclose()
