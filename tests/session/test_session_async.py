"""Async session adapter persistence and cancellation guarantees."""

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path
from textwrap import dedent
from typing import Any
from unittest.mock import MagicMock

import pytest
from filelock import FileLock, Timeout

from nanobot.session import io as session_io
from nanobot.session import manager as session_manager
from nanobot.session.manager import Session, SessionManager, SessionStore


async def _cancel_blocked_mutation(
    task: asyncio.Task[Any],
    *,
    started: threading.Event,
    release: threading.Event,
) -> None:
    assert await asyncio.to_thread(started.wait, 1)
    try:
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "cancellation escaped before the persistence worker settled"
    finally:
        release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)


async def test_concurrent_first_async_gets_share_cached_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    key = "test:concurrent-first-load"
    load_started = threading.Event()
    release_load = threading.Event()
    load_calls = 0

    def delayed_load(loaded_key: str) -> None:
        nonlocal load_calls
        assert loaded_key == key
        load_calls += 1
        load_started.set()
        assert release_load.wait(timeout=1)

    monkeypatch.setattr(manager, "_load", delayed_load)
    first_task = asyncio.create_task(session_io.get_or_create(manager, key))
    try:
        assert await asyncio.to_thread(load_started.wait, 1)
        second_task = asyncio.create_task(session_io.get_or_create(manager, key))
        await asyncio.sleep(0)
        assert not second_task.done()
    finally:
        release_load.set()

    first, second = await asyncio.gather(first_task, second_task)

    assert load_calls == 1
    assert first is second
    assert manager.get_cached(key) is first
    assert await session_io.get_or_create(manager, key) is first


async def test_cancelled_load_settles_before_next_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    key = "test:cancelled-load"
    started = threading.Event()
    release = threading.Event()
    loaded = Session(key=key)
    load_calls = 0

    def blocked_load(loaded_key: str) -> Session:
        nonlocal load_calls
        assert loaded_key == key
        load_calls += 1
        started.set()
        assert release.wait(timeout=1)
        return loaded

    monkeypatch.setattr(manager, "_load", blocked_load)
    cancelled = asyncio.create_task(session_io.get_or_create(manager, key))
    assert await asyncio.to_thread(started.wait, 1)
    cancelled.cancel()
    follower = asyncio.create_task(session_io.get_or_create(manager, key))
    await asyncio.sleep(0)
    assert not cancelled.done()
    assert not follower.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(cancelled, timeout=1)
    assert await asyncio.wait_for(follower, timeout=1) is loaded
    assert load_calls == 1
    assert manager.get_cached(key) is loaded


async def test_async_methods_offload_third_party_store_and_keep_contract(
    tmp_path: Path,
) -> None:
    session = Session(key="test:third-party")
    store = MagicMock(spec=SessionStore)
    store.load.return_value = session
    manager = SessionManager(tmp_path, store=store)
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []

    def load(key: str) -> Session:
        worker_threads.append(threading.get_ident())
        assert key == session.key
        return session

    def save(target: Session, *, fsync: bool = False) -> None:
        worker_threads.append(threading.get_ident())
        assert target is session

    store.load.side_effect = load
    store.save.side_effect = save

    assert await session_io.get_or_create(manager, session.key) is session
    await session_io.save(manager, session, fsync=True)
    await session_io.save_runtime_checkpoint(manager, session)

    store.load.assert_called_once_with(session.key)
    assert store.save.call_args_list[0].kwargs == {"fsync": True}
    assert store.save.call_args_list[1].kwargs == {"fsync": False}
    assert worker_threads
    assert all(thread_id != event_loop_thread for thread_id in worker_threads)


async def test_save_async_cancellation_settles_disk_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    session = Session(key="test:cancel-save")
    session.add_message("user", "persist exactly once")
    started = threading.Event()
    release = threading.Event()
    save_calls = 0
    original_save = manager._store.save

    def blocked_save(target: Session, *, fsync: bool = False) -> None:
        nonlocal save_calls
        save_calls += 1
        started.set()
        assert release.wait(timeout=1)
        original_save(target, fsync=fsync)

    monkeypatch.setattr(manager._store, "save", blocked_save)
    task = asyncio.create_task(session_io.save(manager, session))

    await _cancel_blocked_mutation(task, started=started, release=release)

    assert save_calls == 1
    assert manager.get_cached(session.key) is session
    durable = manager.read_session_file(session.key)
    assert durable is not None
    assert durable["messages"][0]["content"] == "persist exactly once"


async def test_checkpoint_async_cancellation_settles_disk_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("test:cancel-checkpoint")
    session.add_message("user", "question")
    manager.save(session)
    session.metadata["runtime_checkpoint"] = {"phase": "awaiting_tools"}
    started = threading.Event()
    release = threading.Event()
    checkpoint_calls = 0
    original_checkpoint = manager._jsonl_store.save_runtime_checkpoint

    def blocked_checkpoint(target: Session) -> None:
        nonlocal checkpoint_calls
        checkpoint_calls += 1
        started.set()
        assert release.wait(timeout=1)
        original_checkpoint(target)

    monkeypatch.setattr(
        manager._jsonl_store,
        "save_runtime_checkpoint",
        blocked_checkpoint,
    )
    task = asyncio.create_task(session_io.save_runtime_checkpoint(manager, session))

    await _cancel_blocked_mutation(task, started=started, release=release)

    assert checkpoint_calls == 1
    assert manager.get_cached(session.key) is session
    restored = SessionManager(tmp_path).get_or_create(session.key)
    assert restored.metadata["runtime_checkpoint"] == {"phase": "awaiting_tools"}


async def test_same_session_mutations_run_in_submission_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    session = Session(key="test:ordered-mutations")
    save_started = threading.Event()
    release_save = threading.Event()
    checkpoint_started = threading.Event()
    original_save = manager._store.save
    original_checkpoint = manager._jsonl_store.save_runtime_checkpoint

    def blocked_save(target: Session, *, fsync: bool = False) -> None:
        save_started.set()
        assert release_save.wait(timeout=1)
        original_save(target, fsync=fsync)

    def observed_checkpoint(target: Session) -> None:
        checkpoint_started.set()
        original_checkpoint(target)

    monkeypatch.setattr(manager._store, "save", blocked_save)
    monkeypatch.setattr(manager._jsonl_store, "save_runtime_checkpoint", observed_checkpoint)
    save_task = asyncio.create_task(session_io.save(manager, session))
    assert await asyncio.to_thread(save_started.wait, 1)
    checkpoint_task = asyncio.create_task(
        session_io.save_runtime_checkpoint(manager, session)
    )
    await asyncio.sleep(0.01)
    assert not checkpoint_started.is_set()

    release_save.set()
    await asyncio.gather(save_task, checkpoint_task)
    assert checkpoint_started.is_set()


async def test_session_lock_contention_keeps_event_loop_responsive(
    tmp_path: Path,
) -> None:
    manager = SessionManager(tmp_path)
    first = manager.get_or_create("test:blocked-save")
    second = manager.get_or_create("test:cached-session")
    first.add_message("user", "hello")
    lock = manager._jsonl_store._session_files_lock
    assert lock.timeout == 5
    blocker = FileLock(lock.lock_file, timeout=1)
    blocker.acquire()
    save_task = asyncio.create_task(session_io.save(manager, first))
    ticks = 0
    try:
        for _ in range(3):
            await asyncio.sleep(0.01)
            ticks += 1
        assert not save_task.done()
        assert await session_io.get_or_create(manager, second.key) is second
    finally:
        blocker.release()

    await asyncio.wait_for(save_task, timeout=1)
    assert ticks == 3


async def test_local_store_contention_does_not_consume_file_lock_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_manager, "_SESSION_FILES_LOCK_TIMEOUT_SECONDS", 0.05)
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("test:local-contention")
    session.add_message("user", "queued write")
    started = threading.Event()
    release = threading.Event()

    def hold_files() -> None:
        with manager.locked_session_files():
            started.set()
            assert release.wait(timeout=3)

    holder = asyncio.create_task(asyncio.to_thread(hold_files))
    save = None
    try:
        assert await asyncio.to_thread(started.wait, 1)
        save = asyncio.create_task(session_io.save(manager, session))
        await asyncio.sleep(0.2)
        assert not save.done(), "local work must queue instead of timing out on its own store"
    finally:
        release.set()
        await holder
        if save is not None:
            await save

    restored = SessionManager(tmp_path).get_or_create(session.key)
    assert restored.messages[0]["content"] == "queued write"


async def test_external_file_lock_timeout_still_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_manager, "_SESSION_FILES_LOCK_TIMEOUT_SECONDS", 0.05)
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("test:external-contention")
    session.add_message("user", "not saved")
    with FileLock(str(manager.sessions_dir / ".session-files.lock")):
        with pytest.raises(Timeout):
            await session_io.save(manager, session)
    assert manager.read_session_file(session.key) is None


def test_nested_file_transaction_does_not_deadlock_with_queued_save(tmp_path: Path) -> None:
    # A subprocess bounds a lock-order regression without leaving blocked threads
    # in pytest. Handle allocation and Dream pruning both reenter the manager.
    script = dedent('''
        import threading
        import time
        import sys
        from pathlib import Path
        from nanobot.session.manager import SessionManager

        root = Path(sys.argv[1])
        manager = SessionManager(root / "workspace", sessions_root=root / "sessions")
        session = manager.get_or_create("test:nested")
        manager.save(session)
        started = threading.Event()
        finished = threading.Event()

        def save():
            started.set()
            manager.save(session)
            finished.set()

        with manager.locked_session_files():
            threading.Thread(target=save, daemon=True).start()
            assert started.wait(1)
            time.sleep(0.1)
            assert not finished.is_set()
            assert manager.update_session_metadata(session.key, {"handle": "nested"})
        assert finished.wait(2)
        restored = SessionManager(root / "workspace", sessions_root=root / "sessions")
        assert restored.get_or_create(session.key).metadata["handle"] == "nested"
    ''')
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "USERPROFILE": str(tmp_path / "home")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
