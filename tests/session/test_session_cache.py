import asyncio
import gc
import threading
import weakref

from nanobot.session.manager import SESSION_CACHE_MAX_SIZE, SessionManager


def _bounded_manager(tmp_path, limit: int) -> SessionManager:
    manager = SessionManager(tmp_path)
    manager._max_cached_sessions = limit
    return manager


def test_default_session_cache_is_bounded(tmp_path) -> None:
    manager = SessionManager(tmp_path)

    for index in range(SESSION_CACHE_MAX_SIZE + 1):
        manager.get_or_create(f"test:{index}")

    assert len(manager._cache) == SESSION_CACHE_MAX_SIZE


def test_session_cache_releases_inactive_lru_entries(tmp_path) -> None:
    manager = _bounded_manager(tmp_path, 1)
    first = manager.get_or_create("test:first")
    first.add_message("user", "persist me")
    manager.save(first)
    first_ref = weakref.ref(first)

    second = manager.get_or_create("test:second")
    manager.save(second)
    del first
    gc.collect()

    assert len(manager._cache) == 1
    assert first_ref() is None
    assert manager.get_or_create("test:first").messages[0]["content"] == "persist me"


def test_session_cache_keeps_identity_for_evicted_active_sessions(tmp_path) -> None:
    manager = _bounded_manager(tmp_path, 1)
    active = manager.get_or_create("test:active")
    manager.save(active)

    manager.save(manager.get_or_create("test:other"))

    assert manager.get_or_create("test:active") is active


def test_session_cache_refreshes_lru_order_on_access(tmp_path) -> None:
    manager = _bounded_manager(tmp_path, 2)
    manager.save(manager.get_or_create("test:first"))
    manager.save(manager.get_or_create("test:second"))

    manager.get_or_create("test:first")
    manager.save(manager.get_or_create("test:third"))

    assert list(manager._cache) == ["test:first", "test:third"]


def test_flush_all_includes_live_sessions_outside_strong_cache(tmp_path, monkeypatch) -> None:
    manager = _bounded_manager(tmp_path, 1)
    active = manager.get_or_create("test:active")
    manager.save(active)
    manager.save(manager.get_or_create("test:other"))
    saved: list[tuple[str, bool]] = []
    original_save = manager.save

    def recording_save(session, *, fsync=False):
        saved.append((session.key, fsync))
        original_save(session, fsync=fsync)

    monkeypatch.setattr(manager, "save", recording_save)

    assert manager.flush_all() == 2
    assert set(saved) == {("test:active", True), ("test:other", True)}


def test_transient_session_never_reaches_storage(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create_transient("websocket:temporary-test")
    session.add_message("user", "secret")

    manager.save(session, fsync=True)

    assert manager.get_cached(session.key) is session
    assert manager.read_session_file(session.key) is None
    assert list(manager.sessions_dir.glob("*.jsonl")) == []
    manager.invalidate(session.key)
    assert manager.get_cached(session.key) is None


async def test_concurrent_first_async_gets_share_cached_identity(
    tmp_path,
    monkeypatch,
) -> None:
    manager = SessionManager(tmp_path)
    key = "test:concurrent-first-load"
    load_started = threading.Event()
    release_load = threading.Event()
    load_calls = 0

    def delayed_load(loaded_key: str):
        nonlocal load_calls
        assert loaded_key == key
        load_calls += 1
        load_started.set()
        assert release_load.wait(timeout=1)
        return None

    monkeypatch.setattr(manager, "_load", delayed_load)
    first_task = asyncio.create_task(manager.get_or_create_async(key))
    try:
        assert await asyncio.to_thread(load_started.wait, 0.5)
        second_task = asyncio.create_task(manager.get_or_create_async(key))
        await asyncio.sleep(0)
        assert not second_task.done()
    finally:
        release_load.set()

    first, second = await asyncio.gather(first_task, second_task)

    assert load_calls == 1
    assert first is second
    assert manager.get_cached(key) is first
    assert await manager.get_or_create_async(key) is first
