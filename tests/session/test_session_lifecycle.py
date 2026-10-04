"""Regression tests for session stale-write-after-delete invariant.

A Session object belonging to a pre-deletion runtime generation must never
perform durable writes or return to the live cache after delete_session()
completes.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from nanobot.session.manager import Session, SessionManager


def _sm(tmp_path: Path) -> SessionManager:
    return SessionManager(tmp_path)


class _InstrumentedLock:
    """Wraps a real threading.Lock with acquisition observation events.

    holder_acquired: set when the holder thread enters the critical section.
    waiter_blocked: set when a second thread has called acquire() and is
        waiting for the lock (i.e. is genuinely blocked on the real lock).
    """

    def __init__(self, real: threading.Lock):
        self._real = real
        self.holder_acquired = threading.Event()
        self.waiter_blocked = threading.Event()

    def acquire(self, blocking: bool = True) -> bool:
        if self.holder_acquired.is_set() and blocking:
            # A holder already exists; signal that a waiter is now blocked.
            self.waiter_blocked.set()
        result = self._real.acquire(blocking=blocking)
        if result:
            self.holder_acquired.set()
        return result

    def release(self) -> None:
        self._real.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


def _install_instrumented_lock(sm: SessionManager, key: str) -> _InstrumentedLock:
    """Replace the per-key lock for *key* with an instrumented version."""
    real = sm._get_key_lock(key)
    instr = _InstrumentedLock(real)
    sm._key_locks[key] = instr  # type: ignore[assignment]
    return instr


# -- 1. Stale save after delete ----------------------------------------


def test_stale_save_after_delete_must_not_resurrect(tmp_path: Path) -> None:
    """After delete_session completes, save(old) must NOT re-create the session."""
    sm = _sm(tmp_path)
    key = "tg:1"

    old = sm.get_or_create(key)
    old.add_message("user", "hello")
    sm.save(old)
    assert sm.read_session_file(key) is not None

    sm.delete_session(key)
    assert sm.read_session_file(key) is None

    sm.save(old)

    assert sm.read_session_file(key) is None, (
        "stale save re-created deleted session on disk"
    )
    assert sm.get_cached(key) is None, (
        "stale save re-cached deleted session"
    )


# -- 2. Save/delete serialization ---------------------------------------


def test_save_delete_serialized_by_key_lock(tmp_path: Path) -> None:
    """delete_session must block while save is in progress."""
    sm = _sm(tmp_path)
    key = "tg:1"

    s = sm.get_or_create(key)
    s.add_message("user", "data")
    sm.save(s)

    instr = _install_instrumented_lock(sm, key)

    original_store_save = sm._store.save
    save_continue = threading.Event()

    def blocking_save(session, *, fsync=False):
        original_store_save(session, fsync=fsync)
        if not save_continue.wait(timeout=10):
            raise AssertionError("save gate was never released")

    sm._store.save = blocking_save
    s.add_message("assistant", "reply")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_save = pool.submit(sm.save, s)
            f_delete = None

            try:
                assert instr.holder_acquired.wait(timeout=5), "save never acquired lock"
                f_delete = pool.submit(sm.delete_session, key)
                assert instr.waiter_blocked.wait(timeout=5), "delete never blocked"
            finally:
                save_continue.set()

            f_save.result(timeout=5)
            assert f_delete is not None
            assert f_delete.result(timeout=5)
    finally:
        save_continue.set()
        sm._store.save = original_store_save

    assert sm.read_session_file(key) is None


# -- 3. Load/delete serialization ---------------------------------------


def test_load_delete_serialized_by_key_lock(tmp_path: Path) -> None:
    """get_or_create holds lifecycle lock; delete must wait."""
    sm = _sm(tmp_path)
    key = "tg:1"

    original = sm.get_or_create(key)
    original.add_message("user", "data")
    sm.save(original)
    sm.invalidate(key)

    loaded_session = sm._store.load(key)
    assert loaded_session is not None

    instr = _install_instrumented_lock(sm, key)

    load_continue = threading.Event()
    original_load = sm._load

    def intercepted_load(k):
        if k == key:
            if not load_continue.wait(timeout=10):
                raise AssertionError("load gate was never released")
            return loaded_session
        return original_load(k)

    sm._load = intercepted_load

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_get = pool.submit(sm.get_or_create, key)
            f_delete = None

            try:
                assert instr.holder_acquired.wait(timeout=5), (
                    "get_or_create never acquired lock"
                )
                f_delete = pool.submit(sm.delete_session, key)
                assert instr.waiter_blocked.wait(timeout=5), "delete never blocked"
            finally:
                load_continue.set()

            result = f_get.result(timeout=5)
            assert f_delete is not None
            assert f_delete.result(timeout=5)
    finally:
        load_continue.set()
        sm._load = original_load

    sm.save(result)
    assert sm.read_session_file(key) is None, (
        "stale acquired session re-created deleted session"
    )


# -- 4. Same-key recreation ---------------------------------------------


def test_same_key_recreate_stale_cannot_overwrite(tmp_path: Path) -> None:
    """delete -> recreate same key -> stale old save must not overwrite new."""
    sm = _sm(tmp_path)
    key = "tg:1"

    old = sm.get_or_create(key)
    old.add_message("user", "old data")
    sm.save(old)

    sm.delete_session(key)

    new = sm.get_or_create(key)
    new.add_message("user", "brand new")
    sm.save(new)

    sm.save(old)

    reloaded = sm.get_or_create(key)
    assert len(reloaded.messages) == 1, (
        f"Expected 1 msg (new), got {len(reloaded.messages)}"
    )
    assert reloaded.messages[0]["content"] == "brand new"


# -- 5. Stale runtime checkpoint rejected --------------------------------


def test_stale_runtime_checkpoint_rejected(tmp_path: Path) -> None:
    """save_runtime_checkpoint on a deleted session must not resurrect it."""
    sm = _sm(tmp_path)
    key = "tg:1"

    old = sm.get_or_create(key)
    old.add_message("user", "data")
    sm.save(old)

    loaded = sm.get_or_create(key)
    sm.delete_session(key)

    sm.save_runtime_checkpoint(loaded)

    assert sm.read_session_file(key) is None, (
        "stale checkpoint re-created deleted session"
    )


# -- 6. Checkpoint/delete serialization ---------------------------------


def test_checkpoint_delete_serialized(tmp_path: Path) -> None:
    """delete must block while save_runtime_checkpoint is in progress.

    Gates the actual checkpoint write path
    (_jsonl_store.save_runtime_checkpoint) to prove the per-key lock
    serializes checkpoint and delete.
    """
    sm = _sm(tmp_path)
    key = "tg:1"

    s = sm.get_or_create(key)
    s.add_message("user", "data")
    sm.save(s)

    instr = _install_instrumented_lock(sm, key)

    original_cp = sm._jsonl_store.save_runtime_checkpoint
    cp_continue = threading.Event()

    def blocking_cp(session):
        original_cp(session)
        if not cp_continue.wait(timeout=10):
            raise AssertionError("checkpoint gate was never released")

    sm._jsonl_store.save_runtime_checkpoint = blocking_cp

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_cp = pool.submit(sm.save_runtime_checkpoint, s)
            f_delete = None

            try:
                assert instr.holder_acquired.wait(timeout=5), (
                    "checkpoint never acquired lock"
                )
                f_delete = pool.submit(sm.delete_session, key)
                assert instr.waiter_blocked.wait(timeout=5), "delete never blocked"
            finally:
                cp_continue.set()

            f_cp.result(timeout=5)
            assert f_delete is not None
            assert f_delete.result(timeout=5)
    finally:
        cp_continue.set()
        sm._jsonl_store.save_runtime_checkpoint = original_cp

    assert sm.read_session_file(key) is None
    assert not sm._get_runtime_checkpoint_path(key).exists(), (
        "checkpoint sidecar was not cleaned up after delete"
    )


# -- 7. Ordinary save/reload unchanged ----------------------------------


def test_ordinary_save_reload_unchanged(tmp_path: Path) -> None:
    """Normal save/load cycle works unchanged."""
    sm = _sm(tmp_path)
    key = "tg:1"

    s = sm.get_or_create(key)
    s.add_message("user", "hello")
    s.add_message("assistant", "world")
    sm.save(s)

    sm.invalidate(key)
    loaded = sm.get_or_create(key)
    assert len(loaded.messages) == 2
    assert loaded.messages[0]["content"] == "hello"
    assert loaded.messages[1]["content"] == "world"


# -- 8. Third-party store -----------------------------------------------


class _MinimalStore:
    """Minimal in-memory SessionStore for third-party store testing."""

    def __init__(self):
        self._data: dict[str, Session] = {}

    def load(self, key: str) -> Session | None:
        s = self._data.get(key)
        if s is None:
            return None
        return Session(
            key=s.key, messages=list(s.messages),
            created_at=s.created_at, updated_at=s.updated_at,
            metadata=dict(s.metadata), last_consolidated=s.last_consolidated,
        )

    def save(self, session: Session, *, fsync: bool = False) -> None:
        self._data[session.key] = session

    def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def read(self, key: str) -> Any:
        return None

    def read_metadata(self, key: str) -> Any:
        return None

    def update_metadata(self, key: str, updates: dict, *, fsync: bool = False) -> bool:
        return False

    def list_sessions(self) -> list:
        return [{"key": k} for k in self._data]


def test_third_party_store_stale_rejected(tmp_path: Path) -> None:
    """Generation contract works with a third-party SessionStore."""
    store = _MinimalStore()
    sm = SessionManager(tmp_path, store=store)

    key = "tg:1"
    old = sm.get_or_create(key)
    old.add_message("user", "hello")
    sm.save(old)
    assert store.load(key) is not None

    sm.delete_session(key)
    sm.save(old)
    assert store.load(key) is None, "stale saved with third-party store"

    new = sm.get_or_create(key)
    new.add_message("user", "new")
    sm.save(new)
    assert store.load(key) is not None
    assert len(store.load(key).messages) == 1


# -- 9. Fork target generation race -------------------------------------


def test_fork_into_deleted_target_binds_generation(tmp_path: Path) -> None:
    """delete target key -> fork source into same target -> target persists."""
    sm = _sm(tmp_path)
    src_key = "tg:src"
    tgt_key = "tg:tgt"

    src = sm.get_or_create(src_key)
    src.add_message("user", "msg1")
    src.add_message("assistant", "reply1")
    src.add_message("user", "msg2")
    sm.save(src)

    # Pre-create and delete the target key so generation > 0.
    old_tgt = sm.get_or_create(tgt_key)
    old_tgt.add_message("user", "old")
    sm.save(old_tgt)
    sm.delete_session(tgt_key)
    assert sm._generations.get(tgt_key, 0) == 1

    # Fork into the deleted target.
    result = sm.fork_session_before_user_index(src_key, tgt_key, 1)
    assert result is not None

    # Target must exist on disk with the forked data.
    assert sm.read_session_file(tgt_key) is not None, (
        "fork into deleted target did not persist"
    )
    loaded = sm.get_or_create(tgt_key)
    assert len(loaded.messages) == 2  # msg1 + reply1


# -- 10. Dream prune lock-order regression ------------------------------


def test_dream_prune_delete_outside_file_lock(tmp_path: Path) -> None:
    """delete_session must only be called after locked_session_files exits.

    Uses a context-tracking wrapper to prove the file lock is released
    before delete_session is invoked.
    """
    sm = _sm(tmp_path)

    # Create a dream session.
    dream = sm.get_or_create("dream:test1")
    dream.add_message("user", "data")
    sm.save(dream)

    # Patch locked_session_files to track entry/exit.
    file_lock_held = threading.Event()
    file_lock_released = threading.Event()
    original_locked = sm.locked_session_files

    from contextlib import contextmanager

    @contextmanager
    def tracked_locked():
        with original_locked() as d:
            file_lock_held.set()
            try:
                yield d
            finally:
                file_lock_released.set()

    sm.locked_session_files = tracked_locked  # type: ignore[assignment]

    # Patch delete_session to assert file lock is NOT held.
    original_delete = sm.delete_session
    delete_called_after_release = threading.Event()

    def tracked_delete(key: str) -> bool:
        assert not file_lock_held.is_set() or file_lock_released.is_set(), (
            "delete_session called WHILE file lock is held -- ABBA deadlock risk"
        )
        if file_lock_released.is_set():
            delete_called_after_release.set()
        return original_delete(key)

    sm.delete_session = tracked_delete  # type: ignore[assignment]

    from nanobot.agent.memory import MemoryStore

    MemoryStore.prune_dream_sessions(sm, keep=0)

    assert delete_called_after_release.is_set(), (
        "delete_session was never called after file lock release"
    )
