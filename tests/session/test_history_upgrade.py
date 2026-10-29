"""Retired-format diagnostics and continued use of a real 0.4.0-imported database."""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.location import SessionLocation
from nanobot.session.manager import SessionManager
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.webui.session_list_index import list_webui_sessions
from nanobot.webui.transcript import WebUITranscriptRecorder, build_webui_thread_response


@pytest.mark.parametrize("source_kind", ["workspace", "private", "unfinished"])
def test_unconverted_model_history_requires_intermediate_upgrade(tmp_path, source_kind):
    workspace, root = tmp_path / "workspace", tmp_path / "sessions"
    location = SessionLocation(workspace, sessions_root=root)
    directory = workspace / "sessions" if source_kind == "workspace" else location.sessions_dir
    directory.mkdir(exist_ok=True)
    if source_kind == "unfinished":
        # 0.4.x committed the import but crashed before completing source isolation.
        manager = SessionManager(workspace, sessions_root=root)
        with closing(sqlite3.connect(manager.sessions_dir / "sessions.sqlite3")) as db:
            db.execute("INSERT INTO storage_meta VALUES ('jsonl_import', 'complete')")
            db.execute("INSERT INTO storage_meta VALUES ('jsonl_workspace_sources', ?)", (
                '[{"name":"old.jsonl","digest":"' + "0" * 64 + '"}]',
            ))
            db.commit()
    path = directory / "old.jsonl"
    original = b'{"role":"user","content":"retained history"}\n'
    path.write_bytes(original)

    with pytest.raises(RuntimeError, match=r"0\.4\.x.*") as caught:
        SessionManager(workspace, sessions_root=root)
    assert "same config and workspace" in str(caught.value)
    assert path.read_bytes() == original


@pytest.mark.parametrize("segmented", [False, True])
async def test_unconverted_webui_history_requires_intermediate_upgrade(tmp_path, monkeypatch, segmented):
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    directory = tmp_path / "webui"
    directory.mkdir()
    monkeypatch.setattr("nanobot.webui.history.get_webui_dir", lambda: directory)
    path = directory / "websocket_old.jsonl"
    if segmented:
        path = directory / "websocket_old.segments" / "000001.jsonl"
        path.parent.mkdir()
    original = b'{"event":"message","chat_id":"old","text":"retained history"}\n'
    path.write_bytes(original)

    with pytest.raises(RuntimeError, match=r"0\.4\.x.*") as caught:
        await WebUITranscriptRecorder(sessions).initialize()
    assert str(path if not segmented else path.parent) in str(caught.value)
    assert path.read_bytes() == original
    assert sessions.list_sessions() == []


async def test_040_imported_history_survives_restart_paging_fork_and_delete(tmp_path, monkeypatch):
    workspace, root = tmp_path / "workspace", tmp_path / "sessions"
    location = SessionLocation(workspace, sessions_root=root)
    with closing(sqlite3.connect(location.sessions_dir / "sessions.sqlite3")) as db:
        db.executescript((Path(__file__).with_name("fixtures") / "sqlite_v2_040.sql").read_text(encoding="utf-8"))
    directory = tmp_path / "webui"
    directory.mkdir()
    monkeypatch.setattr("nanobot.webui.history.get_webui_dir", lambda: directory)
    # Retained backups may be unreadable by the old parser; SQLite is authoritative.
    paths = [location.sessions_dir / "old.jsonl"]
    paths.extend(directory / f"websocket_{chat}.jsonl" for chat in ("migrated", "display-only", "deleted"))
    for path in paths:
        path.write_bytes(b"retained backup, never read as current history")
    # An interrupted old fork could leave an empty file, skipped by 0.4.x.
    empty = directory / "websocket_empty.jsonl"
    empty.write_bytes(b"")
    segment = directory / "websocket_empty.segments" / "000001.jsonl"
    segment.parent.mkdir()
    segment.write_bytes(b"")
    preference = directory / "sidebar.json"
    preference.write_bytes(b'{"collapsed":true}')
    originals = {path: path.read_bytes() for path in [*paths, empty, segment, preference]}
    key = "websocket:migrated"
    expected = ["first question", "first answer", "second question", "second answer"]
    facts = None
    for _ in range(2):
        sessions = SessionManager(workspace, sessions_root=root)
        await WebUITranscriptRecorder(sessions).initialize()
        assert [message["content"] for message in sessions.read_session_file(key)["messages"]] == expected
        current = sessions.project_history(key, lambda history: history.all_facts())
        assert len(current) == 7
        if facts is not None:
            assert current == facts
        facts = current
        assert sessions.read_session_file("websocket:display-only")["messages"] == []
        rows = list_webui_sessions(sessions, await sessions.state.list_metadata())
        display = next(row for row in rows if row["key"] == "websocket:display-only")
        assert display["preview"] == "display-only answer"
        assert datetime.fromisoformat(display["updated_at"]).timestamp() == 1760000000
        await sessions.state.aclose()

    sessions = SessionManager(workspace, sessions_root=root)
    latest = sessions.project_history(key, lambda history: build_webui_thread_response(key, history=history, limit=1))
    assert latest["page"]["has_more_before"]
    older = sessions.project_history(key, lambda history: build_webui_thread_response(
        key, history=history, limit=1, before=latest["page"]["before_cursor"],
    ))
    assert any(event.get("text") == "second answer" for event in latest["events"])
    assert any(event.get("text") == "first answer" for event in older["events"])
    assert any(event.get("text") == "retained reasoning" for event in older["events"])
    fork = await sessions.state.fork(key, "websocket:fork", 1)
    assert fork is not None
    assert [message["content"] for message in fork.messages] == expected[:2]
    assert (await sessions.state.project_history(fork.key, lambda history: history.all_facts()))[:-1] == facts[:4]
    old = await sessions.state.get(key)
    assert await sessions.state.delete(key)
    with pytest.raises(SessionConflictError):
        await sessions.state.append_history(key, [HistoryFact(HistoryKind.ANSWER, {"text": "late"})], expected_generation=old.generation)
    await sessions.state.aclose()

    for project in (workspace, tmp_path / "new-workspace"):
        reopened = SessionManager(project, sessions_root=root)
        await WebUITranscriptRecorder(reopened).initialize()
        assert reopened.read_session_file(key) is None
        assert reopened.read_session_file("websocket:deleted") is None
    assert {path: path.read_bytes() for path in originals} == originals
