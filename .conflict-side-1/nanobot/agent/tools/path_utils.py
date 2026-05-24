"""Shared path helpers for workspace-scoped tools."""

from pathlib import Path

from nanobot.config.paths import get_media_dir

WORKSPACE_BOUNDARY_NOTE = (
    " (this is a hard policy boundary, not a transient failure; "
    "do not retry with shell tricks or alternative tools, and ask "
    "the user how to proceed if the resource is genuinely required)"
)


def is_under(path: Path, directory: Path) -> bool:
    """Return True when path resolves under directory."""
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def resolve_workspace_path(
    path: str,
    workspace: Path | None = None,
    allowed_dir: Path | None = None,
    extra_allowed_dirs: list[Path] | None = None,
) -> Path:
    """Resolve path against workspace and enforce allowed directory containment."""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir:
        media_path = get_media_dir().resolve()
        all_dirs = [allowed_dir, media_path, *(extra_allowed_dirs or [])]
        if not any(is_under(resolved, d) for d in all_dirs):
            raise PermissionError(
                f"Path {path} is outside allowed directory {allowed_dir}"
                + WORKSPACE_BOUNDARY_NOTE
            )
    return resolved
