"""Session storage location: outside the agent workspace (ADR-0001)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from nanobot.config.loader import load_config
from nanobot.session.location import SessionLocation
from nanobot.session.manager import SessionManager


def _write_legacy_session(
    old_dir: Path,
    key: str,
    content: str,
    *,
    updated_at: str = "2026-01-01T00:00:00",
) -> Path:
    """Write a valid session file in the legacy in-workspace location."""
    old_dir.mkdir(parents=True, exist_ok=True)
    path = old_dir / f"{SessionLocation.storage_key(key)}.jsonl"
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
    assert (manager.sessions_dir / "sessions.sqlite3").exists()
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
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_workspace), str(real_workspace)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(completed.stderr.strip() or completed.stdout.strip())
    else:
        try:
            link_workspace.symlink_to(real_workspace, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlink unavailable: {exc}")

    # Save via the real path, then read via an equivalent directory link.
    manager = SessionManager(workspace=real_workspace)
    session = manager.get_or_create("telegram:1")
    session.add_message("user", "via-real")
    manager.save(session)

    via_link = SessionManager(workspace=link_workspace).get_or_create("telegram:1")
    assert via_link.messages[-1]["content"] == "via-real"


def test_migration_rejects_symlinked_session_file(tmp_path):
    workspace = tmp_path / "workspace"
    path = _write_legacy_session(workspace / "sessions", "cli:test", "original")
    target = tmp_path / "outside.jsonl"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(RuntimeError, match="migration failed"):
        SessionManager(workspace)
    assert "original" in target.read_text()


def test_migration_rejects_symlinked_source_directory(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "sessions").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        SessionManager(workspace)
