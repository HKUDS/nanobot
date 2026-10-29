"""SQLite durability and asynchronous state ownership contracts."""

import asyncio
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from nanobot.session.manager import Session, SessionManager
from nanobot.session.sqlite_store import SessionConflictError


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
    try:
        draft = await state.import_messages("chat:a", [
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
        ])
        draft.add_message("user", "hello")
        await state.prepare_input(draft)
        accepted = manager.read_session_snapshot(draft.key).messages
        assert accepted == draft.messages
        path = manager.sessions_dir / "sessions.sqlite3"
        with sqlite3.connect(path) as db:
            for operation in ("INSERT", "UPDATE", "DELETE"):
                db.execute(f"""CREATE TRIGGER prohibit_{operation.lower()} BEFORE {operation} ON messages
                               BEGIN SELECT RAISE(ABORT, 'rewritten'); END""")
        await state.checkpoint_view(draft, {"step": 1})
    finally:
        await state.aclose()

    stored = manager.read_session_snapshot(draft.key)
    assert stored.messages == accepted
    assert stored.metadata["runtime_checkpoint"] == {"step": 1}


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


def test_committed_version_tracks_history_and_session_replacement(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    key = "websocket:version"
    assert manager.read_session_version(key) is None
    session = manager.get_or_create(key)
    session.messages = [{"role": "user", "content": "first"}]
    manager.save(session)
    first = manager.read_session_version(key)
    assert first == (session.generation, session.revision)
    # Administrative edits may preserve updated_at, so it is not a version token.
    session.messages[0]["content"] = "edited"
    manager.save(session)
    second = manager.read_session_version(key)
    assert second == (first[0], first[1] + 1)
    assert manager.read_session_metadata(key)["updated_at"] == session.updated_at.isoformat()
    manager.delete_session(key)
    assert manager.read_session_version(key) is None
    replacement = manager.get_or_create(key)
    manager.save(replacement)
    assert manager.read_session_version(key) == (replacement.generation, first[1])
    assert replacement.generation != first[0]

    def unexpected_decode(*args, **kwargs):
        pytest.fail("version read decoded history or metadata")

    monkeypatch.setattr("nanobot.session.sqlite_store._object", unexpected_decode)
    assert manager.read_session_version(key) == (replacement.generation, replacement.revision)
