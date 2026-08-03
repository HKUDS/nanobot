import gc
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
