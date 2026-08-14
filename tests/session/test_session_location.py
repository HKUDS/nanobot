"""Session storage location: outside the agent workspace (ADR-0001)."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.config.loader import load_config
from nanobot.session.manager import JsonlSessionStore, SessionManager


def _write_legacy_session(
    old_dir: Path,
    key: str,
    content: str,
    *,
    updated_at: str = "2026-01-01T00:00:00",
) -> Path:
    """Write a valid session file in the legacy in-workspace location."""
    old_dir.mkdir(parents=True, exist_ok=True)
    path = old_dir / f"{JsonlSessionStore.storage_key(key)}.jsonl"
    path.write_text(
        json.dumps(
            {
                "_type": "metadata",
                "key": key,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": updated_at,
                "metadata": {},
                "last_consolidated": 0,
            }
        )
        + "\n"
        + json.dumps({"role": "user", "content": content})
        + "\n",
        encoding="utf-8",
    )
    return path


def test_sessions_are_stored_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace=workspace)

    session = manager.get_or_create("telegram:1")
    session.add_message("user", "hello")
    manager.save(session)

    # The session file must NOT live inside the workspace.
    workspace_sessions = workspace / "sessions"
    assert not workspace_sessions.exists() or not any(workspace_sessions.glob("*.jsonl"))

    # The out-of-workspace store records which workspace it belongs to and the
    # workspace carries only a non-secret stable identity marker.
    marker = manager.sessions_dir / ".workspace"
    assert marker.read_text(encoding="utf-8").strip() == str(workspace.resolve())
    workspace_id = (workspace / ".nanobot" / "workspace-id").read_text(encoding="utf-8").strip()
    assert manager.sessions_dir.name == workspace_id
    assert manager.sessions_dir.parent.name == "sessions"

    # And it must still round-trip through a fresh manager for the same workspace.
    reloaded = SessionManager(workspace=workspace).get_or_create("telegram:1")
    assert reloaded.messages[-1]["content"] == "hello"


def test_workspace_identity_marker_contains_no_session_content(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    secret = f"session-secret-{uuid.uuid4()}"
    manager = SessionManager(workspace=workspace)
    session = manager.get_or_create("telegram:secret")
    session.add_message("user", secret)
    manager.save(session)

    marker = workspace / ".nanobot" / "workspace-id"
    assert marker.read_text(encoding="utf-8").strip() == manager.sessions_dir.name
    assert secret not in marker.read_text(encoding="utf-8")
    assert not any(
        secret in path.read_text(encoding="utf-8")
        for path in workspace.rglob("*")
        if path.is_file()
    )


def test_different_workspaces_are_isolated(tmp_path: Path) -> None:
    workspace_a = tmp_path / "ws_a"
    workspace_b = tmp_path / "ws_b"

    manager_a = SessionManager(workspace=workspace_a)
    session = manager_a.get_or_create("telegram:1")
    session.add_message("user", "secret-for-a")
    manager_a.save(session)

    # A second workspace must not see A's session.
    assert manager_a.sessions_dir != SessionManager(workspace=workspace_b).sessions_dir
    in_b = SessionManager(workspace=workspace_b).get_or_create("telegram:1")
    assert in_b.messages == []


def test_sessions_follow_active_custom_config_data_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    custom_instance = tmp_path / "instance-b"
    custom_config = custom_instance / "config.json"
    default_home = tmp_path / "read-only-home"
    default_home.mkdir()
    default_home.chmod(0o500)
    monkeypatch.setenv("HOME", str(default_home))
    config = load_config(custom_config)
    data_dir = config.runtime_data_dir
    assert data_dir == custom_instance

    manager = SessionManager(
        workspace=tmp_path / "workspace-b",
        sessions_root=data_dir / "sessions",
    )
    session = manager.get_or_create("telegram:custom")
    session.add_message("user", "custom-instance")
    manager.save(session)

    assert manager.sessions_dir.parent == custom_instance / "sessions"
    assert manager._get_session_path(session.key).exists()
    assert not (default_home / ".nanobot" / "sessions").exists()


def test_session_root_inside_workspace_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    with pytest.raises(RuntimeError, match="must be outside the agent workspace"):
        SessionManager(workspace=workspace, sessions_root=workspace / "sessions")


def test_workspace_move_preserves_session_identity(tmp_path: Path) -> None:
    original = tmp_path / "project-old"
    manager = SessionManager(workspace=original)
    session = manager.get_or_create("telegram:1")
    session.add_message("user", "survives-move")
    manager.save(session)

    moved = tmp_path / "project-new"
    original.rename(moved)
    reloaded = SessionManager(workspace=moved)

    assert reloaded.sessions_dir == manager.sessions_dir
    assert reloaded.get_or_create("telegram:1").messages[-1]["content"] == "survives-move"
    assert (reloaded.sessions_dir / ".workspace").read_text(encoding="utf-8").strip() == str(
        moved.resolve()
    )


def test_deleted_workspace_identity_marker_is_recovered(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    manager = SessionManager(workspace=workspace)
    session = manager.get_or_create("telegram:1")
    session.add_message("user", "survives-cleanup")
    manager.save(session)

    shutil.rmtree(workspace / ".nanobot")
    reloaded = SessionManager(workspace=workspace)

    assert reloaded.sessions_dir == manager.sessions_dir
    assert reloaded.get_or_create("telegram:1").messages[-1]["content"] == "survives-cleanup"
    assert (workspace / ".nanobot" / "workspace-id").read_text(encoding="utf-8").strip() == (
        manager.sessions_dir.name
    )


def test_copied_workspace_gets_isolated_session_identity(tmp_path: Path) -> None:
    original = tmp_path / "project-a"
    original.mkdir()
    manager = SessionManager(workspace=original)
    session = manager.get_or_create("telegram:1")
    session.add_message("user", "secret-for-a")
    manager.save(session)

    copied = tmp_path / "project-b"
    shutil.copytree(original, copied)
    copied_manager = SessionManager(workspace=copied)

    assert copied_manager.sessions_dir != manager.sessions_dir
    assert copied_manager.get_or_create("telegram:1").messages == []
    assert (copied / ".nanobot" / "workspace-id").read_text(encoding="utf-8") != (
        original / ".nanobot" / "workspace-id"
    ).read_text(encoding="utf-8")


def test_equivalent_workspace_paths_share_one_store(tmp_path: Path) -> None:
    real_workspace = tmp_path / "real_ws"
    real_workspace.mkdir()
    link_workspace = tmp_path / "link_ws"
    link_workspace.symlink_to(real_workspace, target_is_directory=True)

    # Save via the real path, then read via a symlink to the same directory.
    manager = SessionManager(workspace=real_workspace)
    session = manager.get_or_create("telegram:1")
    session.add_message("user", "via-real")
    manager.save(session)

    via_link = SessionManager(workspace=link_workspace).get_or_create("telegram:1")
    assert via_link.messages[-1]["content"] == "via-real"


def test_legacy_in_workspace_sessions_are_migrated(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    key = "telegram:1"
    old_file = _write_legacy_session(workspace / "sessions", key, "migrated-msg")

    manager = SessionManager(workspace=workspace)

    # The session is readable through the normal store.
    loaded = manager.get_or_create(key)
    assert loaded.messages[-1]["content"] == "migrated-msg"
    # The legacy in-workspace file has been moved away...
    assert not old_file.exists()
    # ...into the out-of-workspace store.
    assert (manager.sessions_dir / old_file.name).exists()

    # Migration is idempotent: a second construction must not corrupt anything.
    again = SessionManager(workspace=workspace).get_or_create(key)
    assert again.messages[-1]["content"] == "migrated-msg"


def test_migration_keeps_source_when_install_fails(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    key = "telegram:partial"
    old_file = _write_legacy_session(workspace / "sessions", key, "still-safe")

    with patch.object(JsonlSessionStore, "_install_snapshot", side_effect=OSError("disk full")):
        manager = SessionManager(workspace=workspace)

    assert old_file.exists()
    assert not (manager.sessions_dir / old_file.name).exists()

    retried = SessionManager(workspace=workspace)
    assert retried.get_or_create(key).messages[-1]["content"] == "still-safe"
    assert not old_file.exists()


def test_migration_preserves_newest_valid_conflict(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    key = "telegram:conflict"
    old_file = _write_legacy_session(workspace / "sessions", key, "newer-workspace")
    manager = SessionManager(workspace=workspace)

    # Recreate an older legacy source while a newer destination already exists.
    manager_session = manager.get_or_create(key)
    manager_session.add_message("assistant", "newer-destination")
    manager.save(manager_session)
    _write_legacy_session(
        workspace / "sessions",
        key,
        "older-workspace",
        updated_at="2025-01-01T00:00:00",
    )

    retried = SessionManager(workspace=workspace)
    loaded = retried.get_or_create(key)

    assert loaded.messages[-1]["content"] == "newer-destination"
    conflicts = list((retried.sessions_dir / ".migration-conflicts").glob("*.jsonl"))
    assert len(conflicts) == 1
    assert "older-workspace" in conflicts[0].read_text(encoding="utf-8")
    assert not old_file.exists()


def test_explicit_rollback_restore_copies_sessions_back_without_deleting_new_store(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace=workspace)
    session = manager.get_or_create("telegram:rollback")
    session.add_message("user", "available-to-old-version")
    manager.save(session, fsync=True)

    result = manager.restore_sessions_to_workspace()
    legacy_file = workspace / "sessions" / manager._get_session_path(session.key).name

    assert result.restored == 1
    assert result.unchanged == 0
    assert result.conflicts == ()
    assert legacy_file.exists()
    assert manager._get_session_path(session.key).exists()
    assert "available-to-old-version" in legacy_file.read_text(encoding="utf-8")

    repeated = manager.restore_sessions_to_workspace()
    assert repeated.restored == 0
    assert repeated.unchanged == 1
    assert repeated.conflicts == ()


def test_legacy_migration_rejects_symlinked_session_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    old_dir = workspace / "sessions"
    old_dir.mkdir(parents=True)
    key = "telegram:symlink"
    outside = _write_legacy_session(tmp_path / "outside", key, "outside-secret")
    source = old_dir / outside.name
    try:
        source.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlink unavailable: {exc}")

    manager = SessionManager(workspace=workspace)

    assert source.is_symlink()
    assert not (manager.sessions_dir / source.name).exists()
    assert manager.get_or_create(key).messages == []


def test_legacy_migration_rejects_symlinked_sessions_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    key = "telegram:directory-symlink"
    outside_file = _write_legacy_session(outside, key, "outside-secret")
    workspace.mkdir()
    try:
        (workspace / "sessions").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    manager = SessionManager(workspace=workspace)

    assert outside_file.exists()
    assert not (manager.sessions_dir / outside_file.name).exists()
    assert manager.get_or_create(key).messages == []
