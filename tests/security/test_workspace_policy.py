from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.security.workspace_policy import (
    WorkspaceBoundaryError,
    is_path_within,
    resolve_allowed_path,
)


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
