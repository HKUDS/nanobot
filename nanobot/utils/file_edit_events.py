"""File-edit activity helpers for WebUI progress events."""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TRACKED_FILE_EDIT_TOOLS = frozenset({"write_file", "edit_file", "notebook_edit"})
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024


@dataclass(slots=True)
class FileSnapshot:
    path: Path
    exists: bool
    text: str | None
    unreadable: bool = False
    binary: bool = False
    oversized: bool = False

    @property
    def countable(self) -> bool:
        return (
            self.text is not None
            and not self.binary
            and not self.oversized
            and not self.unreadable
        )


@dataclass(slots=True)
class FileEditTracker:
    call_id: str
    tool: str
    path: Path
    display_path: str
    before: FileSnapshot


def is_file_edit_tool(tool_name: str | None) -> bool:
    return bool(tool_name) and tool_name in TRACKED_FILE_EDIT_TOOLS


def resolve_file_edit_path(
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> Path | None:
    """Resolve the target file path after tool argument preparation."""
    if not isinstance(params, dict):
        return None
    raw_path = params.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    resolver = getattr(tool, "_resolve", None)
    if callable(resolver):
        try:
            resolved = resolver(raw_path)
            if isinstance(resolved, Path):
                return resolved
            if resolved:
                return Path(resolved)
        except Exception:
            return None
    if workspace is None:
        return Path(raw_path).expanduser().resolve()
    return (workspace / raw_path).expanduser().resolve()


def display_file_edit_path(path: Path, workspace: Path | None) -> str:
    if workspace is not None:
        try:
            return path.resolve().relative_to(workspace.resolve()).as_posix()
        except Exception:
            pass
    return path.as_posix()


def read_file_snapshot(path: Path, *, max_bytes: int = _MAX_SNAPSHOT_BYTES) -> FileSnapshot:
    try:
        if not path.exists() or not path.is_file():
            return FileSnapshot(path=path, exists=False, text="")
        size = path.stat().st_size
        if size > max_bytes:
            return FileSnapshot(path=path, exists=True, text=None, oversized=True)
        raw = path.read_bytes()
    except OSError:
        return FileSnapshot(path=path, exists=path.exists(), text=None, unreadable=True)
    if b"\x00" in raw:
        return FileSnapshot(path=path, exists=True, text=None, binary=True)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return FileSnapshot(path=path, exists=True, text=None, binary=True)
    return FileSnapshot(path=path, exists=True, text=text.replace("\r\n", "\n"))


def line_diff_stats(before: str | None, after: str | None) -> tuple[int, int]:
    """Return ``(added, deleted)`` for a UTF-8 text line-level diff."""
    if before is None or after is None:
        return 0, 0
    before_lines = before.replace("\r\n", "\n").splitlines()
    after_lines = after.replace("\r\n", "\n").splitlines()
    added = 0
    deleted = 0
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            deleted += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, deleted


def prepare_file_edit_tracker(
    *,
    call_id: str,
    tool_name: str,
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> FileEditTracker | None:
    if not is_file_edit_tool(tool_name):
        return None
    path = resolve_file_edit_path(tool, workspace, params)
    if path is None:
        return None
    before = read_file_snapshot(path)
    return FileEditTracker(
        call_id=str(call_id or ""),
        tool=tool_name,
        path=path,
        display_path=display_file_edit_path(path, workspace),
        before=before,
    )


def build_file_edit_start_event(
    tracker: FileEditTracker,
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    predicted_after = _predict_after_text(tracker.tool, params or {}, tracker.before)
    if tracker.before.countable and predicted_after is not None:
        added, deleted = line_diff_stats(tracker.before.text, predicted_after)
    else:
        added, deleted = 0, 0
    return _event_payload(
        tracker,
        phase="start",
        status="editing",
        added=added,
        deleted=deleted,
        approximate=True,
    )


def build_file_edit_end_event(tracker: FileEditTracker) -> dict[str, Any]:
    after = read_file_snapshot(tracker.path)
    if tracker.before.countable and after.countable:
        added, deleted = line_diff_stats(tracker.before.text, after.text)
    else:
        added, deleted = 0, 0
    return _event_payload(
        tracker,
        phase="end",
        status="done",
        added=added,
        deleted=deleted,
        approximate=False,
        binary=after.binary or after.oversized or after.unreadable,
    )


def build_file_edit_error_event(tracker: FileEditTracker, error: str | None = None) -> dict[str, Any]:
    payload = _event_payload(
        tracker,
        phase="error",
        status="error",
        added=0,
        deleted=0,
        approximate=False,
    )
    if error:
        payload["error"] = error.strip()[:240]
    return payload


def _event_payload(
    tracker: FileEditTracker,
    *,
    phase: str,
    status: str,
    added: int,
    deleted: int,
    approximate: bool,
    binary: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": 1,
        "call_id": tracker.call_id,
        "tool": tracker.tool,
        "path": tracker.display_path,
        "phase": phase,
        "added": max(0, int(added)),
        "deleted": max(0, int(deleted)),
        "approximate": bool(approximate),
        "status": status,
    }
    if binary:
        payload["binary"] = True
    return payload


def _predict_after_text(
    tool_name: str,
    params: dict[str, Any],
    before: FileSnapshot,
) -> str | None:
    if not before.countable:
        return None
    before_text = before.text or ""
    if tool_name == "write_file":
        content = params.get("content")
        return content if isinstance(content, str) else ""
    if tool_name == "edit_file":
        old_text = params.get("old_text")
        new_text = params.get("new_text")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            return None
        replace_all = bool(params.get("replace_all"))
        if old_text == "":
            return new_text if not before.exists else before_text
        if old_text in before_text:
            if replace_all:
                return before_text.replace(old_text, new_text)
            return before_text.replace(old_text, new_text, 1)
        return None
    if tool_name == "notebook_edit":
        return _predict_notebook_after_text(params, before_text)
    return None


def _predict_notebook_after_text(params: dict[str, Any], before_text: str) -> str | None:
    try:
        nb = json.loads(before_text) if before_text.strip() else _empty_notebook()
    except Exception:
        return None
    cells = nb.get("cells")
    if not isinstance(cells, list):
        return None
    try:
        cell_index = int(params.get("cell_index", 0))
    except (TypeError, ValueError):
        return None
    new_source = params.get("new_source")
    source = new_source if isinstance(new_source, str) else ""
    cell_type = params.get("cell_type") if params.get("cell_type") in ("code", "markdown") else "code"
    mode = params.get("edit_mode") if params.get("edit_mode") in ("replace", "insert", "delete") else "replace"
    if mode == "delete":
        if 0 <= cell_index < len(cells):
            cells.pop(cell_index)
        else:
            return None
    elif mode == "insert":
        insert_at = min(max(cell_index + 1, 0), len(cells))
        cells.insert(insert_at, _new_notebook_cell(source, str(cell_type)))
    else:
        if not (0 <= cell_index < len(cells)):
            return None
        cell = cells[cell_index]
        if not isinstance(cell, dict):
            return None
        cell["source"] = source
        cell["cell_type"] = cell_type
        if cell_type == "code":
            cell.setdefault("outputs", [])
            cell.setdefault("execution_count", None)
        else:
            cell.pop("outputs", None)
            cell.pop("execution_count", None)
    nb["cells"] = cells
    try:
        return json.dumps(nb, indent=1, ensure_ascii=False)
    except Exception:
        return None


def _empty_notebook() -> dict[str, Any]:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "cells": [],
    }


def _new_notebook_cell(source: str, cell_type: str) -> dict[str, Any]:
    cell: dict[str, Any] = {"cell_type": cell_type, "source": source, "metadata": {}}
    if cell_type == "code":
        cell["outputs"] = []
        cell["execution_count"] = None
    return cell
