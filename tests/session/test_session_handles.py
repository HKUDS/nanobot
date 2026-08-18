from __future__ import annotations

import errno
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import (
    SESSION_HANDLE_DIRECTORY_VERSION,
    SessionHandleDirectory,
    SessionHandleDirectoryError,
    SessionHandleDirectoryProtocol,
    SessionHandleSnapshot,
)


def _save_session(
    sessions: SessionManager,
    key: str,
    *,
    workspace: Path,
    title: str = "",
) -> None:
    session = sessions.get_or_create(key)
    session.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {
        "project_path": str(workspace.resolve()),
        "access_mode": "restricted",
    }
    if title:
        session.metadata["title"] = title
    sessions.save(session, fsync=True)


def test_ensure_persists_public_handle_without_exposing_routing_fields(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    _save_session(
        sessions,
        "websocket:review",
        workspace=project,
        title="代码 审查!",
    )

    directory = SessionHandleDirectory(sessions)
    handle = directory.ensure_many(["websocket:review"])["websocket:review"]
    reloaded = SessionHandleDirectory(sessions).handle_for_session("websocket:review")

    assert isinstance(directory, SessionHandleDirectoryProtocol)
    assert handle.name.isascii() and handle.name.isalpha() and handle.name.islower()
    assert handle.session_key == "websocket:review"
    assert handle.workspace == project.resolve()
    assert 0 <= handle.color_slot < 8
    assert handle.public_payload() == {
        "id": handle.id,
        "name": handle.name,
        "color_slot": handle.color_slot,
    }
    assert reloaded == handle
    stored = json.loads(directory.store_path.read_text(encoding="utf-8"))
    assert stored["version"] == SESSION_HANDLE_DIRECTORY_VERSION
    assert stored["handles"][0]["session_key"] == "websocket:review"

    _save_session(
        sessions,
        "websocket:review",
        workspace=project,
        title="A completely different title",
    )
    assert directory.ensure_many(["websocket:review"])["websocket:review"] == handle


def test_snapshot_batch_uses_one_write_without_session_metadata_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    keys = [f"websocket:{index}" for index in range(4)]
    for key in keys:
        _save_session(sessions, key, workspace=project, title="Worker")
    snapshots = [
        SessionHandleSnapshot(
            session_key=key,
            workspace=project,
        )
        for key in keys
    ]
    directory = SessionHandleDirectory(sessions)
    real_save = directory._save_unlocked
    writes = 0

    def count_save(records) -> None:
        nonlocal writes
        writes += 1
        real_save(records)

    def fail_metadata_read(_key: str) -> None:
        raise AssertionError("trusted snapshots must not reread individual sessions")

    monkeypatch.setattr(directory, "_save_unlocked", count_save)
    monkeypatch.setattr(sessions, "read_session_metadata", fail_metadata_read)

    first = directory.ensure_snapshot_many(snapshots)
    second = directory.ensure_snapshot_many(snapshots)
    reloaded = SessionHandleDirectory(sessions).ensure_snapshot_many(snapshots)

    assert writes == 1
    assert second == first
    assert reloaded == first
    assert len({handle.id for handle in first.values()}) == len(keys)
    assert len({handle.name for handle in first.values()}) == len(keys)
    assert all(
        handle.name.isascii() and handle.name.isalpha() and handle.name.islower()
        for handle in first.values()
    )


def test_names_are_globally_unique_and_resolve_across_workspaces(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    _save_session(sessions, "websocket:left", workspace=left, title="Reviewer")
    _save_session(sessions, "websocket:right", workspace=right, title="Reviewer")
    directory = SessionHandleDirectory(sessions)

    left_handle = directory.ensure_many(["websocket:left"])["websocket:left"]
    right_handle = directory.ensure_many(["websocket:right"])["websocket:right"]

    assert left_handle.name != right_handle.name
    assert directory.resolve(f"@{left_handle.name}") == left_handle
    assert directory.resolve(right_handle.name) == right_handle
    assert directory.resolve("missing") is None


def test_legacy_cross_workspace_name_collision_is_repaired(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    _save_session(sessions, "websocket:left", workspace=left, title="Left")
    _save_session(sessions, "websocket:right", workspace=right, title="Right")
    directory = SessionHandleDirectory(sessions)
    handles = directory.ensure_many(["websocket:left", "websocket:right"])
    stored = json.loads(directory.store_path.read_text(encoding="utf-8"))
    stored["handles"][1]["name"] = stored["handles"][0]["name"]
    directory.store_path.write_text(json.dumps(stored), encoding="utf-8")

    repaired = SessionHandleDirectory(sessions).list_all()

    assert {handle.id for handle in repaired} == {handle.id for handle in handles.values()}
    assert len({handle.name for handle in repaired}) == 2


def test_handles_are_casefold_unique_and_rename_is_not_exposed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    _save_session(sessions, "websocket:first", workspace=project, title="Straße")
    _save_session(sessions, "websocket:second", workspace=project, title="STRASSE")
    directory = SessionHandleDirectory(sessions)

    first = directory.ensure_many(["websocket:first"])["websocket:first"]
    second = directory.ensure_many(["websocket:second"])["websocket:second"]

    assert first.name.casefold() != second.name.casefold()
    assert not hasattr(directory, "rename")


def test_concurrent_allocation_keeps_names_unique(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    keys = [f"websocket:{index}" for index in range(20)]
    for key in keys:
        _save_session(sessions, key, workspace=project, title="Worker")
    directory = SessionHandleDirectory(sessions)

    with ThreadPoolExecutor(max_workers=8) as executor:
        handles = list(
            executor.map(lambda key: directory.ensure_many([key])[key], keys)
        )

    assert len({handle.id for handle in handles}) == len(keys)
    assert len({handle.name.casefold() for handle in handles}) == len(keys)
    assert all(
        handle.name.isascii() and handle.name.isalpha() and handle.name.islower()
        for handle in handles
    )
    assert len(SessionHandleDirectory(sessions).list_all()) == len(keys)


def test_scope_change_rehomes_handle_and_avoids_destination_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nanobot.session.session_handles._HANDLE_NAMES",
        ("mira",),
    )
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    _save_session(sessions, "websocket:moving", workspace=left, title="Worker")
    _save_session(sessions, "websocket:resident", workspace=right, title="Worker")
    directory = SessionHandleDirectory(sessions)
    moving = directory.ensure_many(["websocket:moving"])["websocket:moving"]
    resident = directory.ensure_many(["websocket:resident"])["websocket:resident"]

    _save_session(sessions, "websocket:moving", workspace=right, title="Worker")
    moved = directory.ensure_many(["websocket:moving"])["websocket:moving"]

    assert moved.id == moving.id
    assert moved.workspace == right.resolve()
    assert moved.name == moving.name == "mira"
    assert resident.name == "mira-2"
    assert directory.resolve("mira") == moved
    assert directory.resolve("mira-2") == resident


def test_pool_exhaustion_adds_a_short_numeric_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nanobot.session.session_handles._HANDLE_NAMES",
        ("mira", "nora"),
    )
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    keys = [f"websocket:{index}" for index in range(3)]
    for key in keys:
        _save_session(sessions, key, workspace=project, title="Same title")

    handles = SessionHandleDirectory(sessions).ensure_many(keys)

    assert {handles[key].name for key in keys[:2]} == {"mira", "nora"}
    assert handles[keys[2]].name in {"mira-2", "nora-2"}


def test_missing_session_is_removed_when_resolution_finds_stale_record(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    key = "websocket:stale"
    _save_session(sessions, key, workspace=project, title="Stale")
    directory = SessionHandleDirectory(sessions)
    handle = directory.ensure_many([key])[key]
    assert sessions.delete_session(key) is True

    assert directory.resolve(handle.name) is None
    assert directory.handle_for_session(key) is None
    stored = json.loads(directory.store_path.read_text(encoding="utf-8"))
    assert stored["handles"] == []


def test_atomic_write_tolerates_unsupported_directory_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionManager(tmp_path / "agent")
    _save_session(sessions, "websocket:shared", workspace=project, title="Shared")
    directory = SessionHandleDirectory(sessions)
    real_open = os.open
    real_close = os.close
    real_fsync = os.fsync
    directory_fds: set[int] = set()

    def fake_open(path: str, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if Path(path) == directory.store_path.parent:
            directory_fds.add(fd)
        return fd

    def fake_fsync(fd: int) -> None:
        if fd in directory_fds:
            raise OSError(errno.EINVAL, "Invalid argument")
        real_fsync(fd)

    def fake_close(fd: int) -> None:
        directory_fds.discard(fd)
        real_close(fd)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "close", fake_close)
    monkeypatch.setattr(os, "fsync", fake_fsync)

    handle = directory.ensure_many(["websocket:shared"])["websocket:shared"]

    assert SessionHandleDirectory(sessions).handle_for_session(handle.session_key) == handle


def test_corrupt_store_is_rejected_without_overwriting_it(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path / "agent")
    directory = SessionHandleDirectory(sessions)
    directory.store_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(SessionHandleDirectoryError):
        directory.list_all()

    assert directory.store_path.read_text(encoding="utf-8") == "{broken"
