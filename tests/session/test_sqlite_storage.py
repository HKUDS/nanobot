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
    def write_then_fail() -> None:
        session = Session(key="chat:a", metadata={"runtime_checkpoint": {"step": 1}, "pending_user_followups": [{"id": "x"}]})
        session.add_message("user", "hello")
        manager.save(session)
        raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError):
        manager._store.run_write(write_then_fail)
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
    await state.get("chat:a")
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


def test_duplicate_json_keys_abort_entire_migration(tmp_path):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    path.write_text(
        '{"_type":"metadata","key":"chat:a","key":"chat:b",'
        '"metadata":{},"created_at":"2026-01-01T00:00:00",'
        '"updated_at":"2026-01-01T00:00:00"}\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        SessionManager(workspace, sessions_root=tmp_path / "root")

    database = next((tmp_path / "root").glob("*/sessions.sqlite3"))
    with sqlite3.connect(database) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "sessions" not in tables
        assert "storage_meta" not in tables


def test_nested_duplicate_json_keys_abort_migration(tmp_path):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    path.write_text(
        '{"_type":"metadata","key":"chat:a","metadata":{"title":"a","title":"b"},'
        '"created_at":"2026-01-01T00:00:00",'
        '"updated_at":"2026-01-01T00:00:00"}\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        SessionManager(workspace, sessions_root=tmp_path / "root")


def test_second_provider_state_aborts_migration(tmp_path):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    state = {
        "kind": "responses",
        "provider": "openai",
        "model": "gpt-test",
        "version": 1,
        "payload": {"secret": "opaque"},
        "pending_messages": [],
    }
    with path.open("a", encoding="utf-8") as handle:
        record = json.dumps({"_type": "provider_state", "state": state})
        handle.write(record + "\n" + record + "\n")

    with pytest.raises(RuntimeError, match="migration failed"):
        SessionManager(workspace, sessions_root=tmp_path / "root")


def test_duplicate_sources_with_different_timestamps_abort_migration(tmp_path):
    workspace = tmp_path / "workspace"
    root = tmp_path / "root"
    source = legacy(workspace, key="chat:a")
    location = SessionLocation(workspace, sessions_root=root)
    duplicate = location.sessions_dir / source.name
    duplicate.write_text(
        source.read_text(encoding="utf-8").replace(
            '"updated_at": "2026-01-01T00:00:00"',
            '"updated_at": "2026-01-02T00:00:00"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        SessionManager(workspace, sessions_root=root)
    duplicate.unlink()
    manager = SessionManager(workspace, sessions_root=root)
    assert manager.read_session_snapshot("chat:a") is not None


def test_invalid_migration_marker_fails_closed(tmp_path):
    workspace = tmp_path / "workspace"
    root = tmp_path / "root"
    manager = SessionManager(workspace, sessions_root=root)
    with sqlite3.connect(manager._store.path) as db:
        db.execute(
            "UPDATE storage_meta SET value='corrupt' WHERE key='jsonl_import'"
        )
    legacy(workspace, key="chat:must-not-import")

    with pytest.raises(RuntimeError, match="invalid JSONL migration marker"):
        SessionManager(workspace, sessions_root=root)
    with sqlite3.connect(manager._store.path) as db:
        assert db.execute(
            "SELECT count(*) FROM sessions WHERE key='chat:must-not-import'"
        ).fetchone()[0] == 0


def test_reexport_prunes_deleted_session_and_fresh_store_cannot_resurrect_it(tmp_path):
    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace, sessions_root=tmp_path / "root-a")
    deleted = manager.get_or_create("chat:deleted")
    deleted.add_message("user", "deleted-secret")
    manager.save(deleted)
    kept = manager.get_or_create("chat:kept")
    kept.add_message("user", "keep")
    manager.save(kept)
    assert manager.export_sessions_to_workspace() == 2
    deleted_export = workspace / "sessions" / (
        SessionLocation.storage_key("chat:deleted") + ".jsonl"
    )
    deleted_export.with_suffix(".checkpoint.json").write_text("{}", encoding="utf-8")

    assert manager.delete_session("chat:deleted")
    assert manager.export_sessions_to_workspace() == 1
    assert not deleted_export.exists()
    assert not deleted_export.with_suffix(".checkpoint.json").exists()
    assert "deleted-secret" not in "".join(
        path.read_text(encoding="utf-8")
        for path in (workspace / "sessions").glob("*.jsonl")
    )

    restored = SessionManager(workspace, sessions_root=tmp_path / "root-b")
    assert restored.read_session_snapshot("chat:kept") is not None
    assert restored.read_session_snapshot("chat:deleted") is None


async def test_missing_update_commands_do_not_create_sessions(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    with pytest.raises(SessionConflictError, match="does not exist"):
        await state.update_metadata("chat:missing", {"title": "late"})
    with pytest.raises(SessionConflictError, match="does not exist"):
        await state.record_delivery(
            "chat:missing", "late", {}, expected_generation="deleted-generation",
        )
    assert manager.read_session_snapshot("chat:missing") is None
    await state.aclose()


async def test_delete_rejects_late_delivery_and_metadata(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    session = await state.get("chat:a")
    assert await state.delete(session.key, expected_generation=session.generation)

    with pytest.raises(SessionConflictError):
        await state.record_delivery(
            session.key,
            "deleted-secret",
            {},
            expected_generation=session.generation,
        )
    with pytest.raises(SessionConflictError):
        await state.update_metadata(
            session.key,
            {"secret": "deleted-secret"},
            expected_generation=session.generation,
        )
    assert manager.read_session_snapshot(session.key) is None
    await state.aclose()


async def test_old_generation_cannot_write_into_recreated_key(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    old = await state.get("chat:a")
    assert await state.delete(old.key, expected_generation=old.generation)
    current = await state.get(old.key)
    assert current.generation != old.generation

    with pytest.raises(SessionConflictError, match="replaced session"):
        await state.record_delivery(
            old.key,
            "old result",
            {},
            expected_generation=old.generation,
        )
    loaded = await state.read(old.key)
    assert loaded is not None and loaded.messages == []
    await state.aclose()


async def test_discarded_transient_late_delivery_never_becomes_durable(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    transient = await state.register_transient("temporary:a")
    await state.discard(transient.key)

    with pytest.raises(SessionConflictError):
        await state.record_delivery(
            transient.key,
            "private late result",
            {},
            expected_generation=transient.generation,
        )
    assert manager.read_session_snapshot(transient.key) is None
    await state.aclose()


async def test_read_and_delete_are_serialized_without_cache_ghost(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    state = manager.state
    await state.get("chat:a")
    loaded, release = threading.Event(), threading.Event()
    original = state._load
    first = True

    def paused_load(key, *, history=True):
        nonlocal first
        session = original(key, history=history)
        if first and key == "chat:a":
            first = False
            loaded.set()
            release.wait(5)
        return session

    monkeypatch.setattr(state, "_load", paused_load)
    read = asyncio.create_task(state.read("chat:a"))
    assert await asyncio.to_thread(loaded.wait, 2)
    deletion = asyncio.create_task(state.delete("chat:a"))
    await asyncio.sleep(0.05)
    assert not deletion.done()
    release.set()
    assert await read is not None
    assert await deletion
    assert state.peek("chat:a") is None
    assert manager.read_session_snapshot("chat:a") is None
    await state.aclose()


async def test_synchronous_mutation_is_rejected_after_owner_binds(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    await state.get("chat:a")
    with pytest.raises(RuntimeError, match="async owner"):
        manager.delete_session("chat:a")
    with pytest.raises(RuntimeError, match="async owner"):
        manager.update_session_metadata("chat:a", {"title": "bypass"})
    await state.aclose()


async def test_delivery_requires_explicit_nonempty_generation(tmp_path):
    state = SessionManager(tmp_path).state
    session = await state.get("chat:a")
    with pytest.raises(ValueError, match="requires a session generation"):
        await state.record_delivery(session.key, "unguarded", {}, expected_generation="")
    await state.record_delivery(
        session.key, "current", {}, expected_generation=session.generation,
    )
    assert [message["content"] for message in (await state.get(session.key)).messages] == [
        "current",
    ]
    await state.aclose()
