"""SQLite durability, migration, and asynchronous state ownership contracts."""

import asyncio
import json
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest
from packaging.version import Version

import nanobot.session.jsonl_migration as jsonl_migration
from nanobot.session.jsonl_migration import SUNSET_VERSION, WORKSPACE_BACKUP_DIR
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


def test_import_is_once_and_private_sources_are_unchanged(tmp_path):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    location = SessionLocation(workspace)
    path = path.replace(location.sessions_dir / path.name)
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
    original = path.read_bytes()
    bad = path.parent / "zz-invalid.jsonl"
    bad.write_text("not json")
    with pytest.raises(RuntimeError, match="migration failed"):
        SessionManager(workspace)
    assert path.read_bytes() == original
    bad.unlink()
    manager = SessionManager(workspace)
    assert len(manager.list_sessions()) == 1
    assert not path.exists()
    assert (manager.sessions_dir / WORKSPACE_BACKUP_DIR / path.name).read_bytes() == original


def test_migration_preserves_checkpoint_and_pending_inputs(tmp_path):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    checkpoint = {"version": 1, "session_key": "websocket:old", "base_message_count": 1,
                  "base_updated_at": "2026-01-01T00:00:00", "checkpoint": {"messages": [{"role": "assistant", "content": "partial"}]},
                  "provider_state": None}
    checkpoint_path = path.with_suffix(".checkpoint.json")
    checkpoint_path.write_text(json.dumps(checkpoint))
    original, original_checkpoint = path.read_bytes(), checkpoint_path.read_bytes()
    original_mtime, checkpoint_mtime = path.stat().st_mtime_ns, checkpoint_path.stat().st_mtime_ns
    manager = SessionManager(workspace)
    assert manager.get_or_create("websocket:old").metadata["runtime_checkpoint"] == checkpoint["checkpoint"]
    backup = manager.sessions_dir / WORKSPACE_BACKUP_DIR
    assert (backup / path.name).read_bytes() == original
    assert (backup / checkpoint_path.name).read_bytes() == original_checkpoint
    assert (backup / path.name).stat().st_mtime_ns == original_mtime
    assert (backup / checkpoint_path.name).stat().st_mtime_ns == checkpoint_mtime
    assert not path.exists() and not checkpoint_path.exists()


async def test_workspace_migration_isolates_raw_private_records(tmp_path):
    from nanobot.agent.tools.filesystem import ReadFileTool
    from nanobot.agent.tools.sessions import ReadSessionTool
    from nanobot.providers.base import ProviderConversationState

    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    provider = ProviderConversationState(
        kind="openai_responses", provider="openai", model="gpt-test", version=1,
        payload={"items": [{"encrypted_content": "private-provider-state"}]},
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"_type": "provider_state", "state": provider.to_private_record()}) + "\n")
        handle.write(json.dumps({"role": "tool", "tool_call_id": "call", "content": "private-tool-output"}) + "\n")
    original = path.read_bytes()
    manager = SessionManager(workspace)
    backup = manager.sessions_dir / WORKSPACE_BACKUP_DIR / path.name
    assert not path.exists()
    assert backup.read_bytes() == original
    if sys.platform != "win32":
        assert backup.stat().st_mode & 0o777 == 0o600
        assert backup.parent.stat().st_mode & 0o777 == 0o700

    public = await ReadSessionTool(manager).execute(session_key="websocket:old")
    assert "private-provider-state" not in public and "private-tool-output" not in public
    tool = ReadFileTool(workspace=workspace, allowed_dir=workspace, restrict_to_workspace=True)
    assert (await tool.execute(path=str(path))).is_error
    blocked = await tool.execute(path=str(backup))
    assert blocked.is_error and "outside allowed directory" in blocked
    manager.delete_session("websocket:old")
    assert SessionManager(workspace).read_session_snapshot("websocket:old") is None
    assert backup.read_bytes() == original


def test_restart_finishes_workspace_isolation_after_import_commit(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    root = tmp_path / "root"
    path = legacy(workspace)
    original = path.read_bytes()
    location = SessionLocation(workspace, sessions_root=root)

    def interrupted(*_args):
        raise RuntimeError("interrupted after import commit")

    with monkeypatch.context() as patch:
        patch.setattr(jsonl_migration, "finish_workspace_migration", interrupted)
        with pytest.raises(RuntimeError, match="interrupted after import commit"):
            SessionManager(workspace, sessions_root=root)
    assert path.read_bytes() == original
    with sqlite3.connect(location.sessions_dir / "sessions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
        assert db.execute("SELECT value FROM storage_meta WHERE key='jsonl_import'").fetchone()[0] == "complete"

    manager = SessionManager(workspace, sessions_root=root)
    assert len(manager.list_sessions()) == 1
    assert not path.exists()
    assert (manager.sessions_dir / WORKSPACE_BACKUP_DIR / path.name).read_bytes() == original


def test_workspace_backup_failure_retains_sources_and_retries(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    original = path.read_bytes()

    def failed_backup(*_args):
        raise OSError("backup storage unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(jsonl_migration, "_write_backup", failed_backup)
        with pytest.raises(RuntimeError, match="Could not move legacy sessions"):
            SessionManager(workspace)
    assert path.read_bytes() == original
    manager = SessionManager(workspace)
    assert not path.exists()
    assert (manager.sessions_dir / WORKSPACE_BACKUP_DIR / path.name).read_bytes() == original


def test_restart_finishes_partial_workspace_source_removal(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    checkpoint_path = path.with_suffix(".checkpoint.json")
    checkpoint_path.write_text(json.dumps({"version": 1}))
    original, original_checkpoint = path.read_bytes(), checkpoint_path.read_bytes()
    original_unlink = Path.unlink

    def interrupted_unlink(target, *args, **kwargs):
        if target == checkpoint_path:
            raise OSError("interrupted checkpoint removal")
        return original_unlink(target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupted_unlink)
        with pytest.raises(RuntimeError, match="Could not move legacy sessions"):
            SessionManager(workspace)
    assert not path.exists()
    assert checkpoint_path.read_bytes() == original_checkpoint
    manager = SessionManager(workspace)
    assert len(manager.list_sessions()) == 1
    assert not checkpoint_path.exists()
    backup = manager.sessions_dir / WORKSPACE_BACKUP_DIR
    assert (backup / path.name).read_bytes() == original
    assert (backup / checkpoint_path.name).read_bytes() == original_checkpoint


def test_restart_requires_durable_workspace_source_removal(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    path = legacy(workspace)
    original = path.read_bytes()
    original_sync = SessionLocation.fsync_directory

    def unavailable_directory_sync(directory):
        if directory == path.parent:
            raise OSError("source directory flush unavailable")
        original_sync(directory)

    with monkeypatch.context() as patch:
        patch.setattr(SessionLocation, "fsync_directory", staticmethod(unavailable_directory_sync))
        for _ in range(2):
            with pytest.raises(RuntimeError, match="Could not move legacy sessions"):
                SessionManager(workspace)
            assert not path.exists()
    manager = SessionManager(workspace)
    assert len(manager.list_sessions()) == 1
    assert (manager.sessions_dir / WORKSPACE_BACKUP_DIR / path.name).read_bytes() == original


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


async def test_existing_reads_do_not_wait_for_another_sessions_write_lock(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    await state.get("chat:write")
    await state.get("chat:read")
    await state.update_metadata("chat:read", {"title": "committed"})
    ready, release = threading.Event(), threading.Event()

    def hold():
        with sqlite3.connect(manager._store.path) as db:
            db.execute("BEGIN IMMEDIATE")
            ready.set()
            assert release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    await asyncio.to_thread(ready.wait, 2)
    write = asyncio.create_task(state.update_metadata("chat:write", {"title": "waiting"}))
    try:
        await asyncio.sleep(0)
        metadata = await asyncio.wait_for(state.read_metadata("chat:read"), timeout=2)
        draft = await asyncio.wait_for(state.get("chat:read"), timeout=2)
        header = await asyncio.wait_for(state.get_header("chat:read"), timeout=2)
        assert metadata["metadata"]["title"] == draft.metadata["title"] == header.metadata["title"] == "committed"
        assert not write.done()
    finally:
        release.set()
        await write
        thread.join()
        await state.aclose()


async def test_closing_one_owner_preserves_another_owners_connections(tmp_path):
    from nanobot.session.state import SessionState

    manager = SessionManager(tmp_path)
    first = SessionState(manager._store)
    second = SessionState(manager._store)
    try:
        await first.get("chat:first")
        await second.get("chat:second")
        await first.aclose()
        await second.update_metadata("chat:second", {"title": "still open"})
        assert (await second.get("chat:second")).metadata["title"] == "still open"
    finally:
        await first.aclose()
        await second.aclose()


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


@pytest.mark.parametrize("with_checkpoint", [False, True])
def test_identical_migration_copies_are_imported_once_and_cleaned_up(tmp_path, with_checkpoint):
    workspace = tmp_path / "workspace"
    root = tmp_path / "root"
    source = legacy(workspace, key="chat:a")
    sources = [source]
    if with_checkpoint:
        checkpoint = source.with_suffix(".checkpoint.json")
        checkpoint.write_text(json.dumps({
            "version": 1, "session_key": "chat:a", "base_message_count": 1,
            "base_updated_at": "2026-01-01T00:00:00",
            "checkpoint": {"messages": [{"role": "assistant", "content": "partial"}]},
        }))
        sources.append(checkpoint)
    location = SessionLocation(workspace, sessions_root=root)
    originals = {path.name: path.read_bytes() for path in sources}
    for path in sources:
        shutil.copy2(path, location.sessions_dir / path.name)

    for _ in range(2):
        manager = SessionManager(workspace, sessions_root=root)
        assert len(manager.list_sessions()) == 1
        session = manager.read_session_snapshot("chat:a")
        assert [message["content"] for message in session.messages] == ["hello"]
        if with_checkpoint:
            assert session.metadata["runtime_checkpoint"]["messages"][0]["content"] == "partial"
    for path in sources:
        assert not path.exists()
        assert (location.sessions_dir / path.name).read_bytes() == originals[path.name]
        assert (location.sessions_dir / WORKSPACE_BACKUP_DIR / path.name).read_bytes() == originals[path.name]


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
