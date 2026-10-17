"""Shared path helpers for workspace-scoped tools."""

from pathlib import Path

from nanobot.security.workspace_policy import resolve_allowed_path


def resolve_workspace_path(
    path: str,
    workspace: Path | None = None,
    allowed_dir: Path | None = None,
    extra_allowed_dirs: list[Path] | None = None,
    extra_allowed_files: list[Path] | None = None,
    *,
    media_root: Path | None = None,
) -> Path:
    """Resolve path against workspace and enforce allowed directory containment."""
    media_roots = [media_root] if media_root is not None else []
    extra_roots = [*media_roots, *(extra_allowed_dirs or [])] if allowed_dir else None
    return resolve_allowed_path(
        path,
        workspace=workspace,
        allowed_root=allowed_dir,
        extra_allowed_roots=extra_roots,
        extra_allowed_files=extra_allowed_files,
    )
