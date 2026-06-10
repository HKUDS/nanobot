"""Workspace path boundary helpers.

These helpers are application-level guards.  They make path decisions
consistent across tools, but they are not a replacement for an OS sandbox.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

WORKSPACE_BOUNDARY_NOTE = (
    " (this is a hard policy boundary, not a transient failure; "
    "do not retry with shell tricks or alternative tools, and ask "
    "the user how to proceed if the resource is genuinely required)"
)


class WorkspaceBoundaryError(PermissionError):
    """Raised when a requested path escapes an allowed workspace boundary."""


def resolve_path(path: str | Path, workspace: str | Path | None = None, *, strict: bool = False) -> Path:
    """Resolve *path*, interpreting relative paths against *workspace* when set."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() and workspace is not None:
        candidate = Path(workspace).expanduser() / candidate
    return candidate.resolve(strict=strict)


def is_path_within(path: str | Path, root: str | Path) -> bool:
    """Return True when *path* resolves to *root* or a descendant of *root*."""
    try:
        resolved_path = Path(path).expanduser().resolve(strict=False)
        resolved_root = Path(root).expanduser().resolve(strict=False)
        resolved_path.relative_to(resolved_root)
        return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def is_path_allowed(path: str | Path, roots: Iterable[str | Path]) -> bool:
    """Return True when *path* is inside any allowed root."""
    return any(is_path_within(path, root) for root in roots)


def is_path_exactly_allowed(path: str | Path, files: Iterable[str | Path]) -> bool:
    """Return True when *path* resolves exactly to one of the allowed files."""
    try:
        resolved_path = Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    for file in files:
        try:
            resolved_file = Path(file).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if resolved_path == resolved_file:
            return True
    return False


def require_path_within(
    path: str | Path,
    root: str | Path,
    *,
    message: str | None = None,
) -> Path:
    """Resolve *path* and require it to be inside *root*."""
    resolved = Path(path).expanduser().resolve(strict=False)
    if not is_path_within(resolved, root):
        raise WorkspaceBoundaryError(
            message
            or f"Path {path} is outside allowed directory {Path(root).expanduser()}"
            + WORKSPACE_BOUNDARY_NOTE
        )
    return resolved


def resolve_allowed_path(
    path: str | Path,
    *,
    workspace: str | Path | None = None,
    allowed_root: str | Path | None = None,
    extra_allowed_roots: Iterable[str | Path] | None = None,
    extra_allowed_files: Iterable[str | Path] | None = None,
    strict: bool = False,
) -> Path:
    """Resolve a path and enforce containment in allowed roots when configured."""
    resolved = resolve_path(path, workspace, strict=False)
    files = list(extra_allowed_files or [])
    if allowed_root is None and not files:
        return resolve_path(path, workspace, strict=strict) if strict else resolved

    roots = []
    if allowed_root is not None:
        roots.append(allowed_root)
    roots.extend(extra_allowed_roots or [])
    if not is_path_allowed(resolved, roots) and not is_path_exactly_allowed(resolved, files):
        boundary = Path(allowed_root).expanduser() if allowed_root is not None else "allowed files"
        raise WorkspaceBoundaryError(
            f"Path {path} is outside allowed directory {boundary}"
            + WORKSPACE_BOUNDARY_NOTE
        )
    if strict:
        return resolve_path(path, workspace, strict=True)
    return resolved
