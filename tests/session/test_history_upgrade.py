"""Retired-format diagnostics and continued use of a real 0.4.0-imported database."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.location import SessionLocation
from nanobot.session.manager import SessionManager
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.webui.session_list_index import list_webui_sessions
from nanobot.webui.transcript import build_webui_thread_response


@pytest.mark.parametrize("source_kind", ["workspace", "private", "unfinished"])
def test_unconverted_model_history_requires_intermediate_upgrade(tmp_path, source_kind):
    workspace, root = tmp_path / "workspace", tmp_path / "sessions"
    location = SessionLocation(workspace, sessions_root=root)
    directory = workspace / "sessions" if source_kind == "workspace" else location.sessions_dir
    directory.mkdir(exist_ok=True)
    if source_kind == "unfinished":
        # 0.4.0 committed the import but crashed before completing source isolation.
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

    with pytest.raises(RuntimeError, match=r"0\.4\.0.*") as caught:
        SessionManager(workspace, sessions_root=root)
    assert "same config and workspace" in str(caught.value)
    assert path.read_bytes() == original


def test_inaccessible_model_history_directory_cannot_bypass_upgrade_check(tmp_path, monkeypatch):
    workspace, root = tmp_path / "workspace", tmp_path / "sessions"
    legacy = workspace / "sessions" / "old.jsonl"
    legacy.parent.mkdir(parents=True)
    original = b'{"role":"user","content":"retained history"}\n'
    legacy.write_bytes(original)
    original_iterdir = Path.iterdir

    def restricted_iterdir(path):
        if path == legacy.parent:
            raise PermissionError("synthetic access denial")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", restricted_iterdir)
    with pytest.raises(RuntimeError, match="Cannot inspect legacy session history directory"):
        SessionManager(workspace, sessions_root=root)
    assert legacy.read_bytes() == original


@pytest.mark.parametrize("segmented", [False, True])
def test_unconverted_webui_history_requires_intermediate_upgrade(tmp_path, segmented):
    directory = tmp_path / "webui"
    directory.mkdir()
    path = directory / "websocket_old.jsonl"
    if segmented:
        path = directory / "websocket_old.segments" / "000001.jsonl"
        path.parent.mkdir()
    original = b'{"event":"message","chat_id":"old","text":"retained history"}\n'
    path.write_bytes(original)

    with pytest.raises(RuntimeError, match=r"0\.4\.0.*") as caught:
        SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    assert str(path if not segmented else path.parent) in str(caught.value)
    assert path.read_bytes() == original
    database = next((tmp_path / "sessions").glob("*/sessions.sqlite3"))
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


async def test_040_imported_history_survives_restart_paging_fork_and_delete(tmp_path):
    workspace, root = tmp_path / "workspace", tmp_path / "sessions"
    location = SessionLocation(workspace, sessions_root=root)
    with closing(sqlite3.connect(location.sessions_dir / "sessions.sqlite3")) as db:
        db.executescript((Path(__file__).with_name("fixtures") / "sqlite_v2_040.sql").read_text(encoding="utf-8"))
    directory = tmp_path / "webui"
    directory.mkdir()
    # Retained backups may be unreadable by the old parser; SQLite is authoritative.
    paths = [location.sessions_dir / "old.jsonl"]
    paths.extend(directory / f"websocket_{chat}.jsonl" for chat in ("migrated", "display-only", "deleted"))
    for path in paths:
        path.write_bytes(b"retained backup, never read as current history")
    # An interrupted old fork could leave an empty file, skipped by 0.4.0.
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
        assert reopened.read_session_file(key) is None
        assert reopened.read_session_file("websocket:deleted") is None
    # A new workspace may later create the same key as another workspace's backup.
    fresh = SessionManager(tmp_path / "new-workspace", sessions_root=root)
    new_session = fresh.get_or_create(key)
    new_session.add_message("user", "new workspace conversation")
    fresh.save(new_session)
    restarted = SessionManager(tmp_path / "new-workspace", sessions_root=root)
    assert restarted.read_session_file(key)["messages"][0]["content"] == "new workspace conversation"
    assert {path: path.read_bytes() for path in originals} == originals


def _restore_040_database(workspace: Path, root: Path, *, display_imported: bool) -> Path:
    location = SessionLocation(workspace, sessions_root=root)
    database = location.sessions_dir / "sessions.sqlite3"
    fixture = Path(__file__).with_name("fixtures") / "sqlite_v2_040.sql"
    with closing(sqlite3.connect(database)) as db:
        db.executescript(fixture.read_text(encoding="utf-8"))
        if not display_imported:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("DELETE FROM history_turns")
            db.execute("DELETE FROM history_heads")
            db.execute("DELETE FROM sessions WHERE key != 'websocket:migrated'")
            db.execute("DELETE FROM storage_meta WHERE key LIKE 'webui_history_import_v1%'")
            db.commit()
    return database


def test_foreign_import_receipt_cannot_hide_an_unfinished_workspace(tmp_path):
    root = tmp_path / "sessions"
    first, second = tmp_path / "first", tmp_path / "second"
    _restore_040_database(first, root, display_imported=True)
    second_db = _restore_040_database(second, root, display_imported=False)
    legacy = tmp_path / "webui" / "websocket_migrated.jsonl"
    legacy.parent.mkdir()
    original = b'{"event":"message","chat_id":"migrated","text":"old display"}\n'
    legacy.write_bytes(original)

    with pytest.raises(RuntimeError, match=r"0\.4\.0.*"):
        SessionManager(second, sessions_root=root)
    with closing(sqlite3.connect(second_db)) as db:
        assert db.execute("SELECT count(*) FROM messages WHERE session_key='websocket:migrated'").fetchone()[0] == 4
        assert db.execute("SELECT count(*) FROM history_entries").fetchone()[0] == 0
    assert legacy.read_bytes() == original
    assert SessionManager(first, sessions_root=root).read_session_file("websocket:migrated") is not None


def test_unfinished_display_history_blocks_classic_and_sdk_before_reset(tmp_path):
    workspace = tmp_path / "workspace"
    database = _restore_040_database(workspace, tmp_path / "sessions", display_imported=False)
    legacy = tmp_path / "webui" / "websocket_migrated.jsonl"
    legacy.parent.mkdir()
    original = b'{"event":"message","chat_id":"migrated","text":"old display"}\n'
    legacy.write_bytes(original)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "agents": {"defaults": {"workspace": str(workspace), "provider": "openai", "model": "gpt-4o"}},
        "providers": {"openai": {"apiKey": "fixture-not-a-secret"}},
    }), encoding="utf-8")

    from nanobot import Nanobot

    with pytest.raises(RuntimeError, match=r"0\.4\.0.*"):
        Nanobot.from_config(config)
    env = {key: value for key, value in os.environ.items() if not key.startswith("NANOBOT_")}
    env["PYTHONPATH"] = str(Path(__file__).parents[2])
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "nanobot", "agent", "--config", str(config),
         "--session", "websocket:migrated", "--message", "/new"],
        env=env, text=True, capture_output=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode != 0
    assert "0.4.0" in result.stdout + result.stderr
    with closing(sqlite3.connect(database)) as db:
        messages = db.execute("SELECT record FROM messages WHERE session_key=? ORDER BY position", ("websocket:migrated",)).fetchall()
        assert [json.loads(row[0])["content"] for row in messages] == [
            "first question", "first answer", "second question", "second answer",
        ]
        assert db.execute("SELECT count(*) FROM history_entries").fetchone()[0] == 0
    assert legacy.read_bytes() == original


def test_symlinked_session_root_checks_the_config_instance_webui(tmp_path, create_symlink):
    instance = tmp_path / "instance"
    instance.mkdir()
    target = tmp_path / "external" / "sessions"
    target.mkdir(parents=True)
    root = instance / "sessions"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(root), str(target)],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            pytest.skip(result.stderr.strip() or result.stdout.strip())
    else:
        create_symlink(root, target, target_is_directory=True)
    workspace = instance / "workspace"
    database = _restore_040_database(workspace, root, display_imported=False)
    legacy = instance / "webui" / "websocket_migrated.jsonl"
    legacy.parent.mkdir()
    original = b'{"event":"message","chat_id":"migrated","text":"old display"}\n'
    legacy.write_bytes(original)

    with pytest.raises(RuntimeError, match=r"0\.4\.0.*"):
        SessionManager(workspace, sessions_root=root)
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 4
    assert legacy.read_bytes() == original


@pytest.mark.parametrize("existing_040", [False, True])
def test_foreign_backups_allow_unrelated_workspace_and_later_new_chat(tmp_path, existing_040):
    instance = tmp_path / "instance"
    root = instance / "sessions"
    first, second = tmp_path / "first", tmp_path / "second"
    _restore_040_database(first, root, display_imported=True)
    if existing_040:
        database = _restore_040_database(second, root, display_imported=False)
        with closing(sqlite3.connect(database)) as db:
            db.execute("UPDATE sessions SET key='websocket:other' WHERE key='websocket:migrated'")
            db.execute("UPDATE messages SET session_key='websocket:other' WHERE session_key='websocket:migrated'")
            db.commit()
    legacy = instance / "webui" / "websocket_migrated.jsonl"
    unrelated = instance / "webui" / "websocket_deleted.jsonl"
    legacy.parent.mkdir()
    original = b'{"event":"message","chat_id":"migrated","text":"old display"}\n'
    legacy.write_bytes(original)
    unrelated.write_bytes(b'{"event":"message","chat_id":"deleted","text":"old display"}\n')

    manager = SessionManager(second, sessions_root=root)
    if existing_040:
        assert manager.read_session_file("websocket:other")["messages"][0]["content"] == "first question"
    new_session = manager.get_or_create("websocket:migrated")
    new_session.add_message("user", "new local conversation")
    manager.save(new_session)
    restarted = SessionManager(second, sessions_root=root)
    assert restarted.read_session_file("websocket:migrated")["messages"][0]["content"] == "new local conversation"
    assert legacy.read_bytes() == original

    # An unrelated backup may change without invalidating the unchanged source.
    unrelated.write_bytes(unrelated.read_bytes() + b"\n")
    restarted = SessionManager(second, sessions_root=root)
    assert restarted.read_session_file("websocket:migrated")["messages"][0]["content"] == "new local conversation"
    # Moving the instance preserves ownership even if file metadata changes.
    moved = tmp_path / "moved-instance"
    shutil.move(instance, moved)
    root = moved / "sessions"
    legacy = moved / "webui" / legacy.name
    restarted = SessionManager(second, sessions_root=root)
    assert restarted.read_session_file("websocket:migrated")["messages"][0]["content"] == "new local conversation"

    # A restore can change content while preserving the same file size and mtime.
    old_stat = legacy.stat()
    changed = original.replace(b"old display", b"new display")
    legacy.write_bytes(changed)
    os.utime(legacy, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert (legacy.stat().st_size, legacy.stat().st_mtime_ns) == (old_stat.st_size, old_stat.st_mtime_ns)
    with pytest.raises(RuntimeError, match=r"0\.4\.0.*"):
        SessionManager(second, sessions_root=root)
    assert legacy.read_bytes() == changed


@pytest.mark.parametrize("segmented", [False, True])
def test_inaccessible_webui_history_directory_cannot_bypass_upgrade_check(tmp_path, monkeypatch, segmented):
    workspace = tmp_path / "workspace"
    root = tmp_path / "sessions"
    database = _restore_040_database(workspace, root, display_imported=False)
    directory = tmp_path / "webui"
    directory.mkdir()
    denied = directory
    if segmented:
        denied = directory / "websocket_migrated.segments"
        denied.mkdir()
    source = denied / ("000001.jsonl" if segmented else "websocket_migrated.jsonl")
    source.write_bytes(b'{"event":"message","text":"old display"}\n')
    original_iterdir = Path.iterdir

    def restricted_iterdir(path):
        if path == denied:
            raise PermissionError("synthetic access denial")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", restricted_iterdir)
    with pytest.raises(RuntimeError, match="Cannot inspect legacy WebUI history directory"):
        SessionManager(workspace, sessions_root=root)
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 4



def test_rejected_unconverted_workspace_does_not_block_other_workspace(tmp_path):
    root = tmp_path / "sessions"
    imported, old, fresh = tmp_path / "imported", tmp_path / "old", tmp_path / "fresh"
    _restore_040_database(imported, root, display_imported=True)
    legacy_model = old / "sessions" / "old.jsonl"
    legacy_model.parent.mkdir(parents=True)
    model_bytes = b'{"role":"user","content":"unconverted"}\n'
    legacy_model.write_bytes(model_bytes)
    webui = tmp_path / "webui" / "websocket_migrated.jsonl"
    webui.parent.mkdir()
    display_bytes = b'{"event":"message","text":"imported display"}\n'
    webui.write_bytes(display_bytes)

    with pytest.raises(RuntimeError, match=r"0\.4\.0.*"):
        SessionManager(old, sessions_root=root)
    fresh_sessions = SessionManager(fresh, sessions_root=root)
    assert fresh_sessions.read_session_file("websocket:migrated") is None
    assert legacy_model.read_bytes() == model_bytes
    assert webui.read_bytes() == display_bytes
