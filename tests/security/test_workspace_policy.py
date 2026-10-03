from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nanobot.security.workspace_policy import (
    WorkspaceBoundaryError,
    is_path_within,
    resolve_allowed_path,
)


def _make_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(completed.stderr.strip() or completed.stdout.strip())
        return

    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")


def test_resolve_allowed_path_accepts_workspace_relative_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "src" / "main.py"
    target.parent.mkdir()
    target.write_text("print('ok')", encoding="utf-8")

    resolved = resolve_allowed_path("src/main.py", workspace=workspace, allowed_root=workspace)

    assert resolved == target.resolve()


def test_resolve_allowed_path_blocks_parent_traversal(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(WorkspaceBoundaryError, match="outside allowed directory"):
        resolve_allowed_path("../secret.txt", workspace=workspace, allowed_root=workspace)


def test_resolve_allowed_path_blocks_traversal_shapes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    traversal_shapes: list[str | Path] = [
        "../secret.txt",
        "src/../../secret.txt",
        Path("..") / "secret.txt",
        workspace / "src" / ".." / ".." / "secret.txt",
    ]
    if os.name == "nt":
        traversal_shapes.append("src\\..\\..\\secret.txt")

    for candidate in traversal_shapes:
        with pytest.raises(WorkspaceBoundaryError, match="outside allowed directory"):
            resolve_allowed_path(candidate, workspace=workspace, allowed_root=workspace)


def test_resolve_allowed_path_blocks_prefix_sibling(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sibling = tmp_path / "workspace-other"
    sibling.mkdir()
    secret = sibling / "secret.txt"
    secret.write_text("secret", encoding="utf-8")

    with pytest.raises(WorkspaceBoundaryError, match="outside allowed directory"):
        resolve_allowed_path(secret, workspace=workspace, allowed_root=workspace)


def test_resolve_allowed_path_blocks_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    link = workspace / "linked-secret.txt"
    try:
        link.symlink_to(secret)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert not is_path_within(link, workspace)
    with pytest.raises(WorkspaceBoundaryError):
        resolve_allowed_path("linked-secret.txt", workspace=workspace, allowed_root=workspace)


def test_resolve_allowed_path_allows_extra_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    image = media / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    resolved = resolve_allowed_path(
        image,
        workspace=workspace,
        allowed_root=workspace,
        extra_allowed_roots=[media],
    )

    assert resolved == image.resolve()


def test_resolve_allowed_path_allows_extra_file_only_exactly(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    allowed = outside / "allowed.txt"

    resolved = resolve_allowed_path(
        allowed,
        workspace=workspace,
        allowed_root=workspace,
        extra_allowed_files=[allowed],
    )

    assert resolved == allowed.resolve()
    with pytest.raises(WorkspaceBoundaryError, match="outside allowed directory"):
        resolve_allowed_path(
            allowed / "child.txt",
            workspace=workspace,
            allowed_root=workspace,
            extra_allowed_files=[allowed],
        )


def test_resolve_allowed_path_extra_file_blocks_link_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_target = outside / "MEMORY.md"
    outside_target.write_text("secret", encoding="utf-8")

    memory_link = workspace / "memory"
    _make_directory_link(memory_link, outside)
    logical_allowed = memory_link / "MEMORY.md"

    with pytest.raises(WorkspaceBoundaryError, match="outside allowed directory"):
        resolve_allowed_path(
            "memory/MEMORY.md",
            workspace=workspace,
            allowed_root=workspace / "skills",
            extra_allowed_files=[logical_allowed],
        )
