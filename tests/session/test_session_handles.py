from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from threading import Event

import pytest

from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import (
    SESSION_HANDLE_METADATA_KEY,
    SessionHandleResolver,
    _allocate_name,
    _tier_size,
    normalize_session_handle,
)


def _persist(manager: SessionManager, key: str) -> None:
    manager.save(manager.get_or_create(key))


def _by_key(manager: SessionManager) -> dict[str, str]:
    return {
        handle.session_key: handle.name
        for handle in SessionHandleResolver(manager).list_all()
    }


def test_handle_is_pronounceable_stable_and_stored_with_session(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    _persist(manager, "websocket:review")

    first = SessionHandleResolver(manager).handle_for_session("websocket:review")
    second = SessionHandleResolver(manager).handle_for_session("websocket:review")

    assert first is not None
    assert first == second
    assert first.id.startswith("handle_")
    assert len(first.name) == 4
    assert first.name.isalpha()
    assert "websocket" not in str(first.public_payload())
    metadata = manager.read_session_metadata("websocket:review")
    assert metadata is not None
    assert metadata["metadata"][SESSION_HANDLE_METADATA_KEY] == first.name
    assert not (manager.sessions_dir / "session_handles.json").exists()


def test_pronounceable_tiers_have_millions_of_candidates() -> None:
    assert _tier_size(2) == 2_560
    assert _tier_size(3) == 163_840
    assert _tier_size(4) == 10_485_760


def test_allocator_produces_distinct_short_names() -> None:
    used: set[str] = set()
    for _ in range(100):
        name = _allocate_name(used)
        assert name not in used
        assert name.isalpha()
        assert len(name) == 4
        assert name[:2] != name[2:]
        used.add(name)


def test_existing_handles_do_not_change_when_a_session_is_added(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    _persist(manager, "websocket:first")
    first = _by_key(manager)["websocket:first"]

    _persist(manager, "telegram:second")
    handles = _by_key(manager)

    assert handles["websocket:first"] == first
    assert len(set(handles.values())) == 2


def test_allocating_handle_does_not_populate_session_cache(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sessions_root = tmp_path / "sessions"
    writer = SessionManager(workspace, sessions_root=sessions_root)
    _persist(writer, "websocket:shared")
    resolver_manager = SessionManager(workspace, sessions_root=sessions_root)

    assert resolver_manager.get_cached("websocket:shared") is None
    assert (
        SessionHandleResolver(resolver_manager).handle_for_session("websocket:shared")
        is not None
    )
    assert resolver_manager.get_cached("websocket:shared") is None


def test_deleted_handle_is_reused(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    _persist(manager, "websocket:first")
    _persist(manager, "websocket:second")
    resolver = SessionHandleResolver(manager)
    first_name = _by_key(manager)["websocket:first"]

    assert manager.delete_session("websocket:first")
    _persist(manager, "websocket:third")

    handles = _by_key(manager)
    assert "websocket:first" not in handles
    assert handles["websocket:third"] == first_name
    reused = resolver.resolve(f"@{first_name}")
    assert reused is not None
    assert reused.session_key == "websocket:third"


def test_concurrent_resolvers_do_not_allocate_duplicate_handles(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    for index in range(8):
        _persist(manager, f"websocket:{index}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        snapshots = list(pool.map(
            lambda _: SessionHandleResolver(manager).list_all(),
            range(8),
        ))

    expected = [(handle.name, handle.session_key) for handle in snapshots[0]]
    assert all(
        [(handle.name, handle.session_key) for handle in snapshot] == expected
        for snapshot in snapshots
    )
    assert len({handle.name for handle in snapshots[0]}) == 8


def test_session_snapshot_and_handle_sync_share_one_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    _persist(manager, "websocket:first")
    _persist(manager, "websocket:second")
    resolver = SessionHandleResolver(manager)
    resolver.list_all()
    snapshot_taken = Event()
    release_snapshot = Event()
    original_list = manager.list_sessions

    def paused_list():
        rows = original_list()
        snapshot_taken.set()
        assert release_snapshot.wait(timeout=2)
        return rows

    monkeypatch.setattr(manager, "list_sessions", paused_list)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_sync = pool.submit(resolver.list_all)
        assert snapshot_taken.wait(timeout=2)
        deletion = pool.submit(manager.delete_session, "websocket:first")
        with pytest.raises(FutureTimeout):
            deletion.result(timeout=0.05)
        release_snapshot.set()
        old_sync.result(timeout=2)
        assert deletion.result(timeout=2)


def test_resolver_lists_every_persisted_channel_and_resolves_by_name(
    tmp_path: Path,
) -> None:
    manager = SessionManager(tmp_path)
    _persist(manager, "websocket:first")
    _persist(manager, "telegram:second")
    resolver = SessionHandleResolver(manager)

    handles = resolver.list_all()

    assert {handle.session_key for handle in handles} == {
        "websocket:first",
        "telegram:second",
    }
    for handle in handles:
        assert resolver.resolve(f"@{handle.name}") == handle
    assert resolver.resolve("@zzzz") is None


def test_normalize_session_handle_accepts_optional_at_prefix() -> None:
    assert normalize_session_handle("LUMA") == "luma"
    assert normalize_session_handle("@LUMA") == "luma"
    with pytest.raises(ValueError, match="invalid"):
        normalize_session_handle("aa")
    with pytest.raises(ValueError, match="invalid"):
        normalize_session_handle("not-a-handle")
