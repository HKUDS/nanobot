"""Session storage location: outside the agent workspace (ADR-0001)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.session.manager import JsonlSessionStore, SessionManager


def _write_legacy_session(old_dir: Path, key: str, content: str) -> Path:
    """Write a valid session file in the legacy in-workspace location."""
    old_dir.mkdir(parents=True, exist_ok=True)
    path = old_dir / f"{JsonlSessionStore.storage_key(key)}.jsonl"
    path.write_text(
        json.dumps(
            {
                "_type": "metadata",
                "key": key,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
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

    # The out-of-workspace store records which workspace it belongs to.
    marker = manager.sessions_dir / ".workspace"
    assert marker.read_text(encoding="utf-8") == str(workspace.resolve())

    # And it must still round-trip through a fresh manager for the same workspace.
    reloaded = SessionManager(workspace=workspace).get_or_create("telegram:1")
    assert reloaded.messages[-1]["content"] == "hello"


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
