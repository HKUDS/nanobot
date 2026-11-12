"""Directory metadata for the authenticated WebUI project selector."""

from __future__ import annotations

import heapq
import os
import platform
import socket
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict

from nanobot.security.workspace_access import WorkspaceScopeError


class ProjectDirectory(TypedDict):
    name: str
    path: str


class WorkspaceDirectories(TypedDict):
    path: str
    parent: str | None
    entries: list[ProjectDirectory]
    partial: bool
    truncated: bool
    host: str
    platform: str


def browse_workspace_directories(
    raw_path: str, *, default_workspace: Path, query: str = "", show_hidden: bool = False,
    allow_partial: bool = False,
) -> WorkspaceDirectories:
    """List directories for project selection, independently of agent tool access.

    The caller must authorize project selection. This capability discloses
    directory names under a user-selected root; it never reads file contents or
    changes the selected project or its read/write permissions.
    """
    if "\0" in raw_path:
        raise WorkspaceScopeError("path contains invalid characters")
    path = Path(raw_path).expanduser() if raw_path else default_workspace
    if not path.is_absolute():
        raise WorkspaceScopeError("path must be absolute")
    try:
        prefix = ""
        partial = False
        if allow_partial:
            try:
                is_directory = stat.S_ISDIR(path.stat().st_mode)
            except (FileNotFoundError, NotADirectoryError):
                is_directory = False
            if not is_directory:
                prefix = path.name.casefold()
                path = path.parent
                partial = True
        path = path.resolve(strict=True)
        folded_query = query.casefold()
        def matching_directories() -> Iterator[ProjectDirectory]:
            with os.scandir(path) as entries:
                for entry in entries:
                    name = entry.name.casefold()
                    if not name.startswith(prefix) or folded_query not in name:
                        continue
                    try:
                        if not entry.is_dir():
                            continue
                        hidden = entry.name.startswith(".") or (
                            os.name == "nt"
                            and bool(entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)
                        ) or (
                            sys.platform == "darwin"
                            and bool(entry.stat(follow_symlinks=False).st_flags & stat.UF_HIDDEN)
                        )
                        if show_hidden or prefix.startswith(".") or not hidden:
                            yield {"name": entry.name, "path": entry.path}
                    except OSError:
                        continue

        matches = heapq.nsmallest(501, matching_directories(), key=lambda item: item["name"].casefold())
        return {
            "path": str(path),
            "parent": str(path.parent) if path.parent != path else None,
            "entries": matches[:500],
            "partial": partial,
            "truncated": len(matches) > 500,
            "host": socket.gethostname(),
            "platform": platform.system(),
        }
    except PermissionError as exc:
        raise WorkspaceScopeError("directory is not accessible", status=403) from exc
    except (OSError, RuntimeError) as exc:
        raise WorkspaceScopeError("directory was not found or could not be listed") from exc
