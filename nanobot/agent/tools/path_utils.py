"""Shared path helpers for workspace-scoped tools."""

from pathlib import Path

from nanobot.config.paths import get_media_dir
from nanobot.security.workspace_policy import (
    is_path_within,
    resolve_allowed_path,
)


def is_under(path: Path, directory: Path) -> bool:
    """Return True when path resolves under directory."""
    return is_path_within(path, directory)


def resolve_workspace_path(
    path: str,
    workspace: Path | None = None,
    allowed_dir: Path | None = None,
    extra_allowed_dirs: list[Path] | None = None,
    *,
    include_media_dir: bool = True,
) -> Path:
    """Resolve path against workspace and enforce allowed directory containment."""
    extra_roots = None
    if allowed_dir:
        extra_roots = [
            *([get_media_dir()] if include_media_dir else []),
            *(extra_allowed_dirs or []),
        ]
    return resolve_allowed_path(
        path,
        workspace=workspace,
        allowed_root=allowed_dir,
        extra_allowed_roots=extra_roots,
    )
