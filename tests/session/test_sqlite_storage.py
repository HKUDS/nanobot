"""SQLite durability, migration, and asynchronous state ownership contracts."""

import asyncio
import json
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest
from packaging.version import Version

from nanobot.session.jsonl_migration import SUNSET_VERSION
from nanobot.session.location import SessionLocation
from nanobot.session.manager import Session, SessionManager
from nanobot.session.sqlite_store import SessionConflictError


def legacy(workspace: Path, key: str = "websocket:old", *, content: str = "hello") -> Path:
    directory = workspace / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SessionLocation.storage_key(key)}.jsonl"
    path.write_text(json.dumps({"_type": "metadata", "key": key, "metadata": {"title": "old"},
                               "last_archived": 0, "created_at": "2026-01-01T00:00:00",
                               "updated_at": "2026-01-01T00:00:00"}) + "\n" +
                    json.dumps({"role": "user", "content": content}) + "\n")
    return path


def test_migration_must_be_removed_at_declared_sunset():
    version = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())["project"]["version"]
    assert SUNSET_VERSION == "0.5.0"
    assert Version(Version(version).base_version) < Version(SUNSET_VERSION), (
        "Remove jsonl_migration, its initialization hook, and migration-only tests before 0.5.0"
    )


def test_import_is_once_and_sources_are_unchanged(tmp_path):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    original = path.read_bytes()
    manager = SessionManager(workspace)
    assert manager.read_session_snapshot("websocket:old").messages[0]["content"] == "hello"
    assert path.read_bytes() == original
    manager.delete_session("websocket:old")
    # Reopening must not resurrect deleted conversations, even if the source changes.
    path.write_text("broken legacy file")
    assert SessionManager(workspace).read_session_snapshot("websocket:old") is None


def test_invalid_source_rolls_back_entire_migration(tmp_path):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    bad = path.parent / "zz-invalid.jsonl"
    bad.write_text("not json")
    with pytest.raises(RuntimeError, match="migration failed"):
        SessionManager(workspace)
    bad.unlink()
    manager = SessionManager(workspace)
    assert len(manager.list_sessions()) == 1
    assert path.exists()


def test_migration_preserves_checkpoint_and_pending_inputs(tmp_path):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    checkpoint = {"version": 1, "session_key": "websocket:old", "base_message_count": 1,
                  "base_updated_at": "2026-01-01T00:00:00", "checkpoint": {"messages": [{"role": "assistant", "content": "partial"}]},
                  "provider_state": None}
    path.with_suffix(".checkpoint.json").write_text(json.dumps(checkpoint))
    manager = SessionManager(workspace)
    assert manager.get_or_create("websocket:old").metadata["runtime_checkpoint"] == checkpoint["checkpoint"]


def test_stale_administrative_save_is_rejected(tmp_path):
    manager = SessionManager(tmp_path)
    session = Session(key="chat:a")
    manager.save(session)
    old = manager.get_or_create(session.key)
    session.add_message("user", "new")
    manager.save(session)
    old.add_message("user", "stale")
    with pytest.raises(SessionConflictError):
        manager.save(old)
    assert manager.get_or_create(session.key).messages[-1]["content"] == "new"


def test_transaction_rolls_back_all_rows(tmp_path):
    manager = SessionManager(tmp_path)
    with pytest.raises(RuntimeError):
        with manager.transaction():
            session = Session(key="chat:a", metadata={"runtime_checkpoint": {"step": 1}, "pending_user_followups": [{"id": "x"}]})
            session.add_message("user", "hello")
            manager.save(session)
            raise RuntimeError("injected failure")
    assert manager.list_sessions() == []
    with sqlite3.connect(manager.sessions_dir / "sessions.sqlite3") as db:
        for table in ("sessions", "messages", "checkpoints", "pending_inputs"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


async def test_metadata_updates_preserve_running_turn(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    draft = await state.get("chat:a")
    draft.add_message("user", "hello")
    draft.metadata["pending_user_turn"] = True
    await state.prepare_input(draft)
    await state.update_metadata(draft.key, {"title": "new title"})
    draft.add_message("assistant", "answer")
    await state.finish_turn(draft)
    loaded = await state.get(draft.key)
    assert loaded.metadata["title"] == "new title"
    assert [row["content"] for row in loaded.messages] == ["hello", "answer"]
    assert "pending_user_turn" not in loaded.metadata
    await state.aclose()


async def test_reset_rejects_late_result_and_checkpoint(tmp_path):
    state = SessionManager(tmp_path).state
    draft = await state.get("chat:a")
    draft.add_message("user", "hello")
    await state.prepare_input(draft)
    await state.reset(draft.key)
    draft.add_message("assistant", "late")
    with pytest.raises(SessionConflictError):
        await state.finish_turn(draft)
    with pytest.raises(SessionConflictError):
        await state.checkpoint_view(draft, {"step": 2})
    assert (await state.get(draft.key)).messages == []
    await state.aclose()


async def test_detached_reads_do_not_publish_mutations(tmp_path):
    state = SessionManager(tmp_path).state
    await state.import_messages("chat:a", [{"role": "user", "content": "hello"}])
    draft = await state.get("chat:a")
    draft.messages[0]["content"] = "edited"
    draft.metadata["title"] = "unsaved"
    loaded = await state.get("chat:a")
    assert loaded.messages[0]["content"] == "hello"
    assert "title" not in loaded.metadata
    await state.aclose()


async def test_checkpoint_does_not_rewrite_messages(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    draft = await state.get("chat:a")
    draft.add_message("user", "hello")
    await state.prepare_input(draft)
    path = manager.sessions_dir / "sessions.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER prohibit_rewrite BEFORE UPDATE ON messages BEGIN SELECT RAISE(ABORT, 'rewritten'); END")
    await state.checkpoint_view(draft, {"step": 1})
    assert (await state.get(draft.key)).metadata["runtime_checkpoint"] == {"step": 1}
    await state.aclose()


async def test_database_lock_does_not_block_event_loop(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    await state.update_metadata("chat:a", {"title": "old"})
    ready = threading.Event()
    release = threading.Event()
    def hold():
        with sqlite3.connect(manager.sessions_dir / "sessions.sqlite3") as db:
            db.execute("BEGIN IMMEDIATE")
            ready.set()
            release.wait(5)
    thread = threading.Thread(target=hold)
    thread.start()
    await asyncio.to_thread(ready.wait, 2)
    task = asyncio.create_task(state.update_metadata("chat:a", {"title": "new"}))
    try:
        start = time.monotonic()
        await asyncio.sleep(0.03)
        assert time.monotonic() - start < 0.3
        assert not task.done()
    finally:
        release.set()
        await task
        thread.join()
        await state.aclose()


async def test_cancellation_settles_accepted_write(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    state = manager.state
    ready = threading.Event()
    release = threading.Event()
    original = manager._store.save
    def blocked(session, **kwargs):
        ready.set()
        release.wait(5)
        return original(session, **kwargs)
    monkeypatch.setattr(manager._store, "save", blocked)
    task = asyncio.create_task(state.import_messages("chat:a", [{"role": "user", "content": "accepted"}]))
    await asyncio.to_thread(ready.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await state.get("chat:a")).messages[0]["content"] == "accepted"
    await state.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await state.get("chat:a")


def test_committed_checkpoint_survives_process_exit(tmp_path):
    workspace, root = tmp_path / "workspace", tmp_path / "storage"
    script = '''
import asyncio, os, sys
from pathlib import Path
from nanobot.session.manager import SessionManager
async def main():
    state = SessionManager(Path(sys.argv[1]), sessions_root=Path(sys.argv[2])).state
    draft = await state.get("chat:a")
    draft.add_message("user", "accepted")
    draft.metadata["pending_user_turn"] = True
    await state.prepare_input(draft)
    await state.checkpoint_view(draft, {"step": "tool-finished"})
    os._exit(0)
asyncio.run(main())
'''
    subprocess.run([sys.executable, "-c", script, str(workspace), str(root)], check=True, timeout=15)
    manager = SessionManager(workspace, sessions_root=root)
    session = manager.get_or_create("chat:a")
    assert session.messages[0]["content"] == "accepted"
    assert session.metadata["runtime_checkpoint"] == {"step": "tool-finished"}


async def test_late_metadata_and_summary_cannot_resurrect_deleted_session(tmp_path):
    state = SessionManager(tmp_path).state
    draft = await state.get("chat:deleted")
    await state.delete(draft.key)
    with pytest.raises(SessionConflictError):
        await state.mutate_metadata(
            draft.key, lambda metadata: metadata.update(title="late title"),
            expected_generation=draft.generation,
        )
    with pytest.raises(SessionConflictError):
        await state.commit_summary(draft, "late summary", archive_end=0)
    assert await state.read(draft.key) is None
    await state.aclose()


async def test_large_draft_copy_and_publication_run_on_owner_worker(tmp_path, monkeypatch):
    import nanobot.session.state as owner

    state = SessionManager(tmp_path).state
    draft = await state.get("chat:copy")
    draft.add_message("user", "large transcript" * 10000)
    loop_thread = threading.get_ident()
    original_copy = owner.deepcopy
    copied = threading.Event()

    def checked_copy(value):
        if isinstance(value, Session) or (isinstance(value, dict) and "role" in value):
            assert threading.get_ident() != loop_thread
            copied.set()
        return original_copy(value)

    monkeypatch.setattr(owner, "deepcopy", checked_copy)
    await state.prepare_input(draft)
    await state.checkpoint_view(draft, {"step": 1})
    await state.finish_turn(draft)
    assert copied.is_set()
    assert (await state.read(draft.key)).messages == draft.messages
    await state.aclose()
