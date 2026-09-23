"""File-edit activity helpers for WebUI progress events."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from rapidfuzz.distance import Indel, Opcode, Opcodes

TRACKED_FILE_EDIT_TOOLS = frozenset({"write_file", "edit_file", "apply_patch"})
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
_MAX_DIFF_LINES = 500
_MAX_DIFF_LINE_CHARS = 1200
_DIFF_CONTEXT_LINES = 3


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


@dataclass(slots=True)
class FileDiff:
    """One line alignment shared by edit summaries and activity events."""

    before_lines: list[str]
    after_lines: list[str]
    opcodes: Opcodes
    added: int
    deleted: int

    @classmethod
    def from_text(cls, before: str, after: str) -> FileDiff:
        before_lines = before.replace("\r\n", "\n").splitlines()
        after_lines = after.replace("\r\n", "\n").splitlines()
        opcodes = Indel.opcodes(before_lines, after_lines)
        added = deleted = 0
        for code in opcodes:
            if code.tag in ("replace", "delete"):
                deleted += code.src_end - code.src_start
            if code.tag in ("replace", "insert"):
                added += code.dest_end - code.dest_start
        return cls(before_lines, after_lines, opcodes, added, deleted)

    def matches(self, before: str, after: str) -> bool:
        """Check that an observed file still has the compared line contents."""
        return (
            self.before_lines == before.replace("\r\n", "\n").splitlines()
            and self.after_lines == after.replace("\r\n", "\n").splitlines()
        )

    def _groups(self, context: int) -> Iterator[list[Opcode]]:
        codes = list(self.opcodes)
        if not codes:
            return
        first, last = codes[0], codes[-1]
        if first.tag == "equal":
            codes[0] = Opcode(
                "equal", max(first.src_start, first.src_end - context), first.src_end,
                max(first.dest_start, first.dest_end - context), first.dest_end,
            )
        if last.tag == "equal":
            last = codes[-1]
            codes[-1] = Opcode(
                "equal", last.src_start, min(last.src_end, last.src_start + context),
                last.dest_start, min(last.dest_end, last.dest_start + context),
            )
        group: list[Opcode] = []
        for code in codes:
            tag = code.tag
            i1, i2 = code.src_start, code.src_end
            j1, j2 = code.dest_start, code.dest_end
            if tag == "equal" and i2 - i1 > context * 2:
                group.append(Opcode(tag, i1, i1 + context, j1, j1 + context))
                yield group
                group = []
                i1, j1 = i2 - context, j2 - context
            group.append(Opcode(tag, i1, i2, j1, j2))
        if any(code.tag != "equal" for code in group):
            yield group

    def unified_lines(self, fromfile: str, tofile: str, context: int) -> Iterator[str]:
        if not self.added and not self.deleted:
            return
        yield f"--- {fromfile}"
        yield f"+++ {tofile}"
        for group in self._groups(context):
            first, last = group[0], group[-1]
            old_count = last.src_end - first.src_start
            new_count = last.dest_end - first.dest_start
            old_range = _format_hunk_range(first.src_start + bool(old_count), old_count)
            new_range = _format_hunk_range(first.dest_start + bool(new_count), new_count)
            yield f"@@ -{old_range} +{new_range} @@"
            for code in group:
                if code.tag == "equal":
                    yield from (
                        " " + line for line in self.before_lines[code.src_start:code.src_end]
                    )
                if code.tag in ("replace", "delete"):
                    yield from (
                        "-" + line for line in self.before_lines[code.src_start:code.src_end]
                    )
                if code.tag in ("replace", "insert"):
                    yield from (
                        "+" + line for line in self.after_lines[code.dest_start:code.dest_end]
                    )


class FileEditResult(str):
    """Text observation carrying reusable diffs for the tool's activity hook."""

    file_diffs: dict[Path, FileDiff]

    def __new__(cls, content: str, file_diffs: dict[Path, FileDiff]) -> FileEditResult:
        result = str.__new__(cls, content)
        result.file_diffs = file_diffs
        return result

    def __reduce__(self) -> tuple[type[str], tuple[str]]:
        # Transcript copies and persistence carry only the model observation.
        return str, (str(self),)


def is_file_edit_tool(tool_name: str | None) -> bool:
    return bool(tool_name) and tool_name in TRACKED_FILE_EDIT_TOOLS


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
    diff = FileDiff.from_text(before, after)
    return diff.added, diff.deleted


def build_unified_diff_payload(
    before: str | None,
    after: str | None,
    *,
    fromfile: str = "before",
    tofile: str = "after",
    context_lines: int = _DIFF_CONTEXT_LINES,
    max_lines: int = _MAX_DIFF_LINES,
    max_line_chars: int = _MAX_DIFF_LINE_CHARS,
    diff: FileDiff | None = None,
) -> dict[str, Any] | None:
    """Return a compact standard unified diff for WebUI rendering."""
    if before is None or after is None:
        return None
    if diff is None:
        diff = FileDiff.from_text(before, after)
    diff_lines = list(diff.unified_lines(fromfile, tofile, max(0, int(context_lines))))
    if not diff_lines:
        return None

    limited_lines, truncated, emitted_body_lines = _limit_unified_diff_lines(
        diff_lines,
        max_lines=max_lines,
        max_line_chars=max_line_chars,
    )
    if emitted_body_lines == 0:
        return None
    return {
        "format": "unified",
        "context": context_lines,
        "truncated": truncated,
        "text": "\n".join(limited_lines),
    }


def _limit_unified_diff_lines(
    diff_lines: list[str],
    *,
    max_lines: int,
    max_line_chars: int,
) -> tuple[list[str], bool, int]:
    """Limit unified diff body lines without inventing a wire-level hunk schema."""
    body_limit = max(0, int(max_lines))
    line_char_limit = max(0, int(max_line_chars))
    limited: list[str] = []
    emitted_body_lines = 0
    truncated = False
    index = 0

    while index < len(diff_lines):
        line = diff_lines[index]
        if not line.startswith("@@ "):
            limited.append(line)
            index += 1
            continue

        hunk_header = line
        hunk_body: list[str] = []
        index += 1
        while index < len(diff_lines) and not diff_lines[index].startswith("@@ "):
            hunk_body.append(diff_lines[index])
            index += 1

        remaining = body_limit - emitted_body_lines
        if remaining <= 0:
            truncated = True
            break

        selected_body = hunk_body[:remaining]
        if len(selected_body) < len(hunk_body):
            truncated = True

        selected_body, truncated_line = _limit_unified_diff_line_chars(
            selected_body,
            max_line_chars=line_char_limit,
        )
        truncated = truncated or truncated_line
        limited.append(
            hunk_header
            if len(selected_body) == len(hunk_body)
            else _rewrite_hunk_header_for_body(hunk_header, selected_body)
        )
        limited.extend(selected_body)
        emitted_body_lines += len(selected_body)

        if truncated and emitted_body_lines >= body_limit:
            break

    return limited, truncated, emitted_body_lines


def _limit_unified_diff_line_chars(
    lines: list[str],
    *,
    max_line_chars: int,
) -> tuple[list[str], bool]:
    if max_line_chars <= 0:
        return lines, False

    limited: list[str] = []
    truncated = False
    for line in lines:
        if not line or line[0] not in (" ", "+", "-"):
            limited.append(line)
            continue
        marker = line[0]
        content = line[1:]
        if len(content) > max_line_chars:
            limited.append(f"{marker}{content[:max_line_chars]}")
            truncated = True
        else:
            limited.append(line)
    return limited, truncated


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_lines>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_lines>\d+))? @@(?P<section>.*)$"
)


def _rewrite_hunk_header_for_body(header: str, body: list[str]) -> str:
    match = _HUNK_HEADER_RE.match(header)
    if match is None:
        return header

    old_lines = 0
    new_lines = 0
    for line in body:
        if not line:
            continue
        marker = line[0]
        if marker in (" ", "-"):
            old_lines += 1
        if marker in (" ", "+"):
            new_lines += 1

    old_start = int(match.group("old_start"))
    new_start = int(match.group("new_start"))
    section = match.group("section")
    return (
        f"@@ -{_format_hunk_range(old_start, old_lines)} "
        f"+{_format_hunk_range(new_start, new_lines)} @@{section}"
    )


def _format_hunk_range(start: int, line_count: int) -> str:
    return str(start) if line_count == 1 else f"{start},{line_count}"


def prepare_file_edit_trackers(
    *,
    call_id: str,
    tool_name: str,
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> list[FileEditTracker]:
    if not isinstance(params, dict) or not is_file_edit_tool(tool_name):
        return []
    paths = resolve_file_edit_paths(tool_name, tool, workspace, params)
    display_workspace = _display_workspace(tool, workspace)
    trackers: list[FileEditTracker] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        before = read_file_snapshot(path)
        trackers.append(FileEditTracker(
            call_id=str(call_id or ""),
            tool=tool_name,
            path=path,
            display_path=display_file_edit_path(path, display_workspace),
            before=before,
        ))
    return trackers


def resolve_file_edit_paths(
    tool_name: str,
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> list[Path]:
    if not isinstance(params, dict):
        return []
    if tool_name == "apply_patch":
        return _resolve_apply_patch_paths(tool, workspace, params)
    if tool_name not in {"write_file", "edit_file"}:
        return []
    path = _resolve_single_path(tool, workspace, params.get("path"))
    return [path] if path is not None else []


def _resolve_apply_patch_paths(
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any],
) -> list[Path]:
    if params.get("dry_run") is True:
        return []
    edits = params.get("edits")
    if not isinstance(edits, list):
        return []
    patch_edits = cast(list[Any], edits)
    paths: list[Path] = []
    seen: set[Path] = set()
    for edit in patch_edits:
        if not isinstance(edit, dict):
            continue
        raw_path = cast(dict[str, Any], edit).get("path")
        if not isinstance(raw_path, str):
            continue
        raw_path = raw_path.strip()
        if not raw_path or "\0" in raw_path:
            continue
        path = _resolve_single_path(tool, workspace, raw_path)
        if path is not None and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _resolve_single_path(tool: Any, workspace: Path | None, raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    resolver = getattr(tool, "_resolve_write", None)
    if callable(resolver):
        try:
            resolved = resolver(raw_path)
            if isinstance(resolved, Path):
                return resolved
            if resolved:
                return Path(cast(str, resolved))
        except Exception:
            return None
    resolver = getattr(tool, "_resolve", None)
    if callable(resolver):
        try:
            resolved = resolver(raw_path)
            if isinstance(resolved, Path):
                return resolved
            if resolved:
                return Path(cast(str, resolved))
        except Exception:
            return None
    if workspace is None:
        return Path(raw_path).expanduser().resolve()
    return (workspace / raw_path).expanduser().resolve()


def _display_workspace(tool: Any, fallback: Path | None) -> Path | None:
    resolver = getattr(tool, "_display_workspace", None)
    if callable(resolver):
        try:
            value = resolver()
        except Exception:
            return fallback
        if isinstance(value, Path):
            return value
        if value:
            return Path(cast(str, value))
    return fallback


def build_file_edit_start_event(
    tracker: FileEditTracker,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _event_payload(
        tracker,
        phase="start",
        status="editing",
        added=0,
        deleted=0,
        approximate=True,
    )


def build_file_edit_end_event(
    tracker: FileEditTracker,
    params: dict[str, Any] | None = None,
    *,
    diff: FileDiff | None = None,
) -> dict[str, Any]:
    after = read_file_snapshot(tracker.path)
    diff_payload: dict[str, Any] | None = None
    if (
        tracker.before.countable and after.countable
        and tracker.before.text is not None and after.text is not None
    ):
        if diff is None or not diff.matches(tracker.before.text, after.text):
            diff = FileDiff.from_text(tracker.before.text, after.text)
        added, deleted = diff.added, diff.deleted
        diff_payload = build_unified_diff_payload(
            tracker.before.text,
            after.text,
            fromfile=tracker.display_path,
            tofile=tracker.display_path,
            diff=diff,
        )
        binary = False
    else:
        added, deleted = 0, 0
        binary = (
            tracker.before.binary
            or tracker.before.oversized
            or tracker.before.unreadable
            or after.binary
            or after.oversized
            or after.unreadable
        )
    payload = _event_payload(
        tracker,
        phase="end",
        status="done",
        added=added,
        deleted=deleted,
        approximate=False,
        binary=binary,
        operation="delete" if tracker.before.exists and not after.exists else None,
    )
    if diff_payload is not None:
        payload["diff"] = diff_payload
    return payload


def build_file_edit_error_event(
    tracker: FileEditTracker,
    error: str | None = None,
) -> dict[str, Any]:
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
    operation: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": 1,
        "call_id": tracker.call_id,
        "tool": tracker.tool,
        "path": tracker.display_path,
        "absolute_path": tracker.path.as_posix(),
        "phase": phase,
        "added": max(0, int(added)),
        "deleted": max(0, int(deleted)),
        "approximate": bool(approximate),
        "status": status,
    }
    if binary:
        payload["binary"] = True
    if operation:
        payload["operation"] = operation
    return payload
