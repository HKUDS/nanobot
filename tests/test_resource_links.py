from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from filelock import Timeout

from nanobot import resource_links
from nanobot.resource_links import ResourceView, ensure_resource_view


def _targets(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    data_dir = tmp_path / "state"
    config_path = data_dir / "config.json"
    agent_workspace = tmp_path / "agent"
    package_root = tmp_path / "package"
    agent_workspace.mkdir()
    package_root.mkdir()
    return data_dir, config_path, agent_workspace, package_root


def _ensure(
    data_dir: Path,
    config_path: Path,
    agent_workspace: Path,
    package_root: Path,
) -> ResourceView:
    return ensure_resource_view(
        data_dir=data_dir,
        config_path=config_path,
        agent_workspace=agent_workspace,
        package_root=package_root,
    )


def _remove_directory_link(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        os.rmdir(path)


def test_ensure_resource_view_is_stable_and_idempotent(tmp_path: Path) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)

    first = _ensure(data_dir, config_path, agent_workspace, package_root)
    second = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert first == second
    assert first.warnings == ()
    assert first.root is not None
    assert len(first.root.name) == 16
    assert first.agent is not None
    assert first.agent.resolve(strict=True) == agent_workspace.resolve(strict=True)
    assert first.media is not None
    assert first.media.resolve(strict=True) == (data_dir / "media").resolve(strict=True)
    assert first.package is not None
    assert first.package.resolve(strict=True) == package_root.resolve(strict=True)


def test_resource_view_id_isolated_by_config_workspace_and_package(tmp_path: Path) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    other_workspace = tmp_path / "other-agent"
    other_package = tmp_path / "other-package"
    other_workspace.mkdir()
    other_package.mkdir()

    baseline = _ensure(data_dir, config_path, agent_workspace, package_root)
    config_variant = _ensure(
        data_dir,
        data_dir / "other-config.json",
        agent_workspace,
        package_root,
    )
    workspace_variant = _ensure(data_dir, config_path, other_workspace, package_root)
    package_variant = _ensure(data_dir, config_path, agent_workspace, other_package)

    roots = {
        baseline.root,
        config_variant.root,
        workspace_variant.root,
        package_variant.root,
    }
    assert None not in roots
    assert len(roots) == 4


def test_partial_link_failure_only_degrades_that_alias(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    real_create = resource_links._create_directory_link

    def fail_media(alias: Path, target: Path) -> None:
        if alias.name == "media":
            raise PermissionError("media denied")
        real_create(alias, target)

    monkeypatch.setattr(resource_links, "_create_directory_link", fail_media)

    view = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert view.root is not None
    assert view.agent is not None
    assert view.media is None
    assert view.package is not None
    assert any("media denied" in warning for warning in view.warnings)


def test_existing_alias_collision_is_never_replaced(tmp_path: Path) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    first = _ensure(data_dir, config_path, agent_workspace, package_root)
    assert first.agent is not None
    _remove_directory_link(first.agent)
    first.agent.write_text("user-owned", encoding="utf-8")

    second = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert second.root == first.root
    assert second.agent is None
    assert second.media is not None
    assert second.package is not None
    assert first.agent.read_text(encoding="utf-8") == "user-owned"
    assert any("alias collision for agent" in warning for warning in second.warnings)


def test_wrong_link_is_never_repointed(tmp_path: Path) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    wrong_target = tmp_path / "wrong-agent"
    wrong_target.mkdir()
    first = _ensure(data_dir, config_path, agent_workspace, package_root)
    assert first.agent is not None
    _remove_directory_link(first.agent)
    resource_links._create_directory_link(first.agent, wrong_target)

    second = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert second.agent is None
    assert first.agent.resolve(strict=True) == wrong_target.resolve(strict=True)
    assert any("alias collision for agent" in warning for warning in second.warnings)


def test_unmanaged_namespace_collision_is_not_modified(tmp_path: Path) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    namespace = data_dir / "resources"
    namespace.mkdir(parents=True)
    user_file = namespace / "notes.txt"
    user_file.write_text("keep me", encoding="utf-8")

    view = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert view.root is None
    assert view.agent is None
    assert user_file.read_text(encoding="utf-8") == "keep me"
    assert list(namespace.iterdir()) == [user_file]
    assert any("ownership marker missing" in warning for warning in view.warnings)


def test_mismatched_view_marker_is_not_repaired(tmp_path: Path) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    first = _ensure(data_dir, config_path, agent_workspace, package_root)
    assert first.root is not None
    marker = first.root / ".nanobot-resource-view.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["targets"]["agent"] = str(tmp_path / "someone-else")
    marker.write_text(json.dumps(payload), encoding="utf-8")

    second = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert second.root is None
    assert second.agent is None
    assert any("marker does not match" in warning for warning in second.warnings)


def test_invalid_marker_encoding_degrades_without_raising(tmp_path: Path) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    first = _ensure(data_dir, config_path, agent_workspace, package_root)
    assert first.root is not None
    marker = first.root / ".nanobot-resource-view.json"
    marker.write_bytes(b"\xff")

    second = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert second.root is None
    assert any("Could not read resource view marker" in warning for warning in second.warnings)


def test_failed_marker_write_removes_only_new_empty_view_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    real_write_marker = resource_links._write_marker

    def fail_view_marker(marker_path: Path, payload: dict) -> None:
        if marker_path.name == resource_links._VIEW_MARKER:
            raise PermissionError("view marker denied")
        real_write_marker(marker_path, payload)

    monkeypatch.setattr(resource_links, "_write_marker", fail_view_marker)

    view = _ensure(data_dir, config_path, agent_workspace, package_root)

    namespace = data_dir / "resources"
    assert view.root is None
    assert namespace.is_dir()
    assert [entry.name for entry in namespace.iterdir()] == [
        resource_links._NAMESPACE_MARKER
    ]
    assert any("view marker denied" in warning for warning in view.warnings)


def test_view_inside_agent_target_is_fully_disabled_to_avoid_recursive_walk(
    tmp_path: Path,
) -> None:
    agent_workspace = tmp_path / "agent"
    data_dir = agent_workspace / ".nanobot"
    config_path = data_dir / "config.json"
    package_root = tmp_path / "package"
    agent_workspace.mkdir()
    package_root.mkdir()

    view = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert view.root is None
    assert view.agent is None
    assert view.media is None
    assert view.package is None
    assert not (data_dir / "resources").exists()
    assert any("recursive traversal unsafe" in warning for warning in view.warnings)


def test_unverified_new_link_is_removed_without_touching_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    real_points_to = resource_links._link_points_to

    def fail_agent_verification(alias: Path, target: Path) -> bool:
        if alias.name == "agent":
            return False
        return real_points_to(alias, target)

    monkeypatch.setattr(resource_links, "_link_points_to", fail_agent_verification)

    view = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert view.root is not None
    assert view.agent is None
    assert not os.path.lexists(view.root / "agent")
    assert agent_workspace.is_dir()
    assert view.media is not None
    assert view.package is not None
    assert any("could not be verified" in warning for warning in view.warnings)


def test_lock_timeout_is_nonfatal_and_finite(monkeypatch, tmp_path: Path) -> None:
    data_dir, config_path, agent_workspace, package_root = _targets(tmp_path)
    observed_timeouts: list[float] = []

    def fail_lock(lock_path: str, *, timeout: float):
        observed_timeouts.append(timeout)
        raise Timeout(lock_path)

    monkeypatch.setattr(resource_links, "FileLock", fail_lock)

    view = _ensure(data_dir, config_path, agent_workspace, package_root)

    assert observed_timeouts == [resource_links._LOCK_TIMEOUT_SECONDS]
    assert view == ResourceView(
        warnings=(
            f"Timed out waiting for resource view lock: "
            f"{data_dir.resolve() / '.nanobot-resource-links.lock'}",
        )
    )


def test_windows_symlink_failure_falls_back_to_junction(monkeypatch, tmp_path: Path) -> None:
    alias = tmp_path / "alias"
    target = tmp_path / "target"
    target.mkdir()
    junction_calls: list[tuple[Path, Path]] = []

    def fail_symlink(self: Path, target: Path, *, target_is_directory: bool = False) -> None:
        assert target_is_directory is True
        raise PermissionError("symlinks unavailable")

    def record_junction(link: Path, junction_target: Path) -> None:
        junction_calls.append((link, junction_target))

    monkeypatch.setattr(Path, "symlink_to", fail_symlink)
    monkeypatch.setattr(resource_links, "_is_windows", lambda: True)
    monkeypatch.setattr(resource_links, "_create_windows_junction", record_junction)

    resource_links._create_directory_link(alias, target)

    assert junction_calls == [(alias, target)]


def test_windows_junction_command_timeout_is_bounded(monkeypatch, tmp_path: Path) -> None:
    observed_timeouts: list[float] = []

    def time_out(command: str, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(resource_links.subprocess, "run", time_out)

    with pytest.raises(OSError, match="Timed out creating Windows junction"):
        resource_links._create_windows_junction(tmp_path / "alias", tmp_path / "target")

    assert observed_timeouts == [resource_links._JUNCTION_TIMEOUT_SECONDS]


def test_default_package_root_points_to_installed_nanobot_package(tmp_path: Path) -> None:
    data_dir = tmp_path / "state"
    agent_workspace = tmp_path / "agent"
    agent_workspace.mkdir()

    view = ensure_resource_view(
        data_dir=data_dir,
        config_path=data_dir / "config.json",
        agent_workspace=agent_workspace,
    )

    assert view.package is not None
    assert view.package.resolve(strict=True) == Path(resource_links.__file__).parent.resolve(strict=True)
