"""Path evidence extraction for WebUI file preview resolution.

When the LLM references a local file with a relative path whose implied base
(the directory it actually worked in) differs from the session's bound project
root, the preview resolver falls back to directories the agent actually
touched during the turn. The evidence comes from tool call arguments already
persisted in the session transcript, so the fallback is deterministic and
needs no extra storage.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from nanobot.security.workspace_access import WorkspaceScope
from nanobot.security.workspace_policy import (
    WorkspaceBoundaryError,
    resolve_allowed_path,
)

logger = logging.getLogger(__name__)

# File-like tools whose arguments carry a filesystem path that establishes the
# directory the agent is actually working in.  `exec` is deliberately excluded:
# its `command` argument is a shell string, not a reliable path base.
EVIDENCE_TOOLS = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "apply_patch",
        "list_dir",
        "find_files",
    }
)

# How many recent messages to scan for evidence.  The reference base shifts as
# the turn changes, so only the most recent activity is meaningful.  This keeps
# the scan bounded for long sessions.
MAX_EVIDENCE_MESSAGES = 80

# How many ancestor levels of a touched path are kept as candidate bases.
# A tool call under .../project/sub/dir/file.md yields bases
# .../project/sub/dir, .../project/sub, .../project — covering both
# same-directory references and references like "sub/dir/file.md" from the
# project root.
EVIDENCE_ANCESTOR_LEVELS = 3


def extract_path_evidence(messages: Sequence[dict[str, Any]] | None) -> list[Path]:
    """Return directories the agent touched, most recent first, deduplicated.

    Evidence is collected from ``tool_calls`` entries of recent assistant
    messages: the ``path`` argument of each file-like tool contributes its
    parent directories as candidate reference bases.
    """
    if not messages:
        return []
    evidence: list[Path] = []
    seen: set[Path] = set()

    def add_candidate(path: Path) -> None:
        if path in seen:
            return
        seen.add(path)
        evidence.append(path)

    for message in reversed(messages[-MAX_EVIDENCE_MESSAGES:]):
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        calls = cast(list[dict[str, Any]], tool_calls)
        for call in calls:
            function = call.get("function")
            if not isinstance(function, dict):
                continue
            function_data = cast(dict[str, Any], function)
            name = function_data.get("name")
            if not isinstance(name, str) or name not in EVIDENCE_TOOLS:
                continue
            raw_args = function_data.get("arguments")
            if not isinstance(raw_args, str):
                continue
            path = _extract_path_argument(name, raw_args)
            if path is None:
                continue
            for base in _evidence_directories(name, path):
                add_candidate(base)
    return evidence


def _extract_path_argument(tool_name: str, raw_args: str) -> str | None:
    try:
        parsed = json.loads(raw_args)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    args = cast(dict[str, Any], parsed)
    value = args.get("path")
    if not isinstance(value, str) or not value:
        # find_files also accepts positional glob patterns, but only an
        # explicit `path` establishes a directory base.
        return None
    return value


def _evidence_directories(tool_name: str, raw_path: str) -> Iterable[Path]:
    """Return candidate base directories for one tool call, nearest first."""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        # Relative tool paths resolve against the project root; they carry no
        # cross-directory base information, so they are not evidence.
        return ()
    # list_dir/find_files take a directory as their path; file tools take a
    # file, whose parent is the working directory.
    start = candidate if tool_name in {"list_dir", "find_files"} else candidate.parent
    return _ancestors(start)


def _ancestors(start: Path) -> Iterable[Path]:
    """Yield *start* and its ancestors up to EVIDENCE_ANCESTOR_LEVELS deep."""
    current = start
    for _ in range(EVIDENCE_ANCESTOR_LEVELS):
        yield current
        parent = current.parent
        if parent == current:  # filesystem root
            break
        current = parent


def resolve_with_evidence(
    rel_path: str,
    evidence_dirs: Iterable[Path],
    *,
    scope: WorkspaceScope,
) -> Path | None:
    """Resolve *rel_path* against evidence dirs, most recent base first.

    Each candidate base is joined with the relative path, then the result must
    pass the workspace boundary check (restricted mode: the resolved file must
    stay inside the project root) and exist as a file.  The first hit wins;
    ``None`` means no candidate resolved.
    """
    clean = rel_path.strip().strip("/")
    if not clean:
        return None
    for base in evidence_dirs:
        candidate = base / clean
        try:
            resolved = resolve_allowed_path(
                candidate,
                workspace=scope.project_path,
                allowed_root=scope.project_path if scope.restrict_to_workspace else None,
                strict=True,
            )
        except (FileNotFoundError, WorkspaceBoundaryError, OSError):
            # Boundary violations are skipped rather than surfaced: an
            # evidence dir that escapes the workspace is not a usable base.
            continue
        if resolved.is_file():
            return resolved
    return None
