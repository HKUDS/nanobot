"""Structured patch editing tool for coding workflows."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from nanobot.agent.tools.base import tool_parameters
from nanobot.agent.tools.filesystem import _FsTool
from nanobot.agent.tools.schema import BooleanSchema, StringSchema, tool_parameters_schema


PatchKind = Literal["add", "delete", "update"]


@dataclass(slots=True)
class _Hunk:
    header: str | None
    lines: list[tuple[str, str]]


@dataclass(slots=True)
class _PatchOp:
    kind: PatchKind
    path: str
    new_path: str | None = None
    add_lines: list[str] | None = None
    hunks: list[_Hunk] | None = None


@dataclass(slots=True)
class _PatchSummary:
    action: str
    path: str
    added: int = 0
    deleted: int = 0
    new_path: str | None = None


class _PatchError(ValueError):
    pass


_ABSOLUTE_WINDOWS_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_file_header(line: str) -> bool:
    return (
        line.startswith("*** Add File: ")
        or line.startswith("*** Delete File: ")
        or line.startswith("*** Update File: ")
    )


def _validate_relative_path(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        raise _PatchError("patch path cannot be empty")
    if "\0" in normalized:
        raise _PatchError(f"patch path contains a null byte: {path!r}")
    if normalized.startswith(("~", "/", "\\")) or _ABSOLUTE_WINDOWS_RE.match(normalized):
        raise _PatchError(f"patch path must be relative: {path}")
    if any(part == ".." for part in re.split(r"[\\/]+", normalized)):
        raise _PatchError(f"patch path must not contain '..': {path}")
    return normalized


def _lines_to_text(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _text_line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _line_diff_stats(before: str, after: str) -> tuple[int, int]:
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


def _format_summary(summary: _PatchSummary) -> str:
    path = (
        f"{summary.path} -> {summary.new_path}"
        if summary.new_path
        else summary.path
    )
    stats = ""
    if summary.added or summary.deleted:
        stats = f" (+{summary.added}/-{summary.deleted})"
    return f"- {summary.action} {path}{stats}"


def _parse_patch(patch: str) -> list[_PatchOp]:
    lines = patch.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0] != "*** Begin Patch":
        raise _PatchError("patch must start with '*** Begin Patch'")
    if len(lines) < 2 or lines[-1] != "*** End Patch":
        raise _PatchError("patch must end with '*** End Patch'")

    ops: list[_PatchOp] = []
    i = 1
    end = len(lines) - 1
    while i < end:
        line = lines[i]
        if line.startswith("*** Add File: "):
            path = _validate_relative_path(line.removeprefix("*** Add File: "))
            i += 1
            add_lines: list[str] = []
            while i < end and not _is_file_header(lines[i]):
                if not lines[i].startswith("+"):
                    raise _PatchError(f"Add File lines must start with '+': {lines[i]!r}")
                add_lines.append(lines[i][1:])
                i += 1
            ops.append(_PatchOp(kind="add", path=path, add_lines=add_lines))
            continue

        if line.startswith("*** Delete File: "):
            path = _validate_relative_path(line.removeprefix("*** Delete File: "))
            ops.append(_PatchOp(kind="delete", path=path))
            i += 1
            continue

        if line.startswith("*** Update File: "):
            path = _validate_relative_path(line.removeprefix("*** Update File: "))
            i += 1
            new_path: str | None = None
            if i < end and lines[i].startswith("*** Move to: "):
                new_path = _validate_relative_path(lines[i].removeprefix("*** Move to: "))
                i += 1

            hunks: list[_Hunk] = []
            while i < end and not _is_file_header(lines[i]):
                if not lines[i].startswith("@@"):
                    raise _PatchError(f"Update File sections require '@@' hunks: {lines[i]!r}")
                header = lines[i][2:].strip() or None
                i += 1
                hunk_lines: list[tuple[str, str]] = []
                while i < end and not lines[i].startswith("@@") and not _is_file_header(lines[i]):
                    if lines[i] == "*** End of File":
                        i += 1
                        break
                    if lines[i] == r"\ No newline at end of file":
                        i += 1
                        continue
                    if not lines[i] or lines[i][0] not in {" ", "+", "-"}:
                        raise _PatchError(f"Hunk lines must start with ' ', '+', or '-': {lines[i]!r}")
                    hunk_lines.append((lines[i][0], lines[i][1:]))
                    i += 1
                if not hunk_lines:
                    raise _PatchError(f"Update File hunk is empty: {path}")
                hunks.append(_Hunk(header=header, lines=hunk_lines))
            if not hunks and new_path is None:
                raise _PatchError(f"Update File requires at least one hunk or Move to: {path}")
            ops.append(_PatchOp(kind="update", path=path, new_path=new_path, hunks=hunks))
            continue

        raise _PatchError(f"unknown patch header: {line!r}")

    if not ops:
        raise _PatchError("patch contains no file operations")
    return ops


def _find_with_eof_fallback(content: str, needle: str, start: int) -> tuple[int, int]:
    pos = content.find(needle, start)
    if pos >= 0:
        return pos, len(needle)
    if needle.endswith("\n"):
        trimmed = needle[:-1]
        pos = content.find(trimmed, start)
        if pos >= 0 and pos + len(trimmed) == len(content):
            return pos, len(trimmed)
    return -1, 0


def _line_offset(content: str, line_number: int) -> int:
    if line_number <= 1:
        return 0
    offset = 0
    for current, line in enumerate(content.splitlines(keepends=True), start=1):
        if current >= line_number:
            return offset
        offset += len(line)
    return len(content)


def _line_hint(header: str | None) -> int | None:
    if not header:
        return None
    match = re.search(r"-(\d+)(?:,\d+)?", header)
    return int(match.group(1)) if match else None


def _hunk_mismatch(path: str, old_text: str, content: str, header: str | None) -> str:
    lines = content.splitlines(keepends=True)
    old_lines = old_text.splitlines(keepends=True)
    window = max(1, len(old_lines))
    best_ratio, best_start = -1.0, 0
    best_lines: list[str] = []
    for i in range(max(1, len(lines) - window + 1)):
        current = lines[i : i + window]
        ratio = difflib.SequenceMatcher(None, "".join(old_lines), "".join(current)).ratio()
        if ratio > best_ratio:
            best_ratio, best_start, best_lines = ratio, i, current

    label = f" after header {header!r}" if header else ""
    if best_ratio <= 0:
        return f"hunk does not match {path}{label}"
    diff = "\n".join(difflib.unified_diff(
        old_lines,
        best_lines,
        fromfile="patch hunk",
        tofile=f"{path} (actual, line {best_start + 1})",
        lineterm="",
    ))
    return (
        f"hunk does not match {path}{label}. "
        f"Best match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
    )


def _apply_hunks(path: str, content: str, hunks: list[_Hunk]) -> str:
    cursor = 0
    for hunk in hunks:
        old_lines = [text for marker, text in hunk.lines if marker in {" ", "-"}]
        new_lines = [text for marker, text in hunk.lines if marker in {" ", "+"}]
        old_text = _lines_to_text(old_lines)
        new_text = _lines_to_text(new_lines)

        search_start = cursor
        line_hint = None
        if hunk.header:
            line_hint = _line_hint(hunk.header)
            if line_hint is not None:
                search_start = _line_offset(content, line_hint)
            else:
                header_pos = content.find(hunk.header, cursor)
                if header_pos >= 0:
                    search_start = header_pos

        if old_text:
            pos, match_len = _find_with_eof_fallback(content, old_text, search_start)
            if pos < 0 and search_start != 0 and line_hint is None:
                pos, match_len = _find_with_eof_fallback(content, old_text, 0)
            if pos < 0:
                raise _PatchError(_hunk_mismatch(path, old_text, content, hunk.header))
        else:
            pos = search_start
            match_len = 0

        content = content[:pos] + new_text + content[pos + match_len:]
        cursor = pos + len(new_text)
    return content


@tool_parameters(
    tool_parameters_schema(
        patch=StringSchema(
            "Full patch text. Use *** Begin Patch / *** End Patch and file sections "
            "for Add File, Update File, Delete File, and optional Move to.",
            min_length=1,
        ),
        dry_run=BooleanSchema(
            description="Validate and summarize the patch without writing files.",
            default=False,
        ),
        required=["patch"],
    )
)
class ApplyPatchTool(_FsTool):
    """Apply a structured multi-file patch."""
    _scopes = {"core", "subagent"}

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "Default tool for code edits. Apply a structured patch with "
            "*** Begin Patch and *** End Patch. Supports Add File, Update File, "
            "Delete File, and Move to across one or more files. Use this for "
            "multi-file changes, structural edits, generated code, or any edit "
            "where a reviewable patch is clearer than an exact replacement. "
            "Paths must be relative. Set dry_run=true to validate and preview "
            "the change summary without writing files. Use edit_file only for "
            "small exact replacements copied from read_file."
        )

    async def execute(self, patch: str, dry_run: bool = False, **kwargs: Any) -> str:
        try:
            ops = _parse_patch(patch)
            writes: dict[Path, str] = {}
            deletes: set[Path] = set()
            summaries: list[_PatchSummary] = []

            for op in ops:
                source = self._resolve(op.path)
                if op.kind == "add":
                    if source.exists() or source in writes:
                        raise _PatchError(f"file to add already exists: {op.path}")
                    new_content = _lines_to_text(op.add_lines or [])
                    writes[source] = new_content
                    deletes.discard(source)
                    summaries.append(_PatchSummary(
                        action="add",
                        path=op.path,
                        added=_text_line_count(new_content),
                    ))
                    continue

                if op.kind == "delete":
                    pending_content = writes.get(source)
                    if pending_content is None and not source.exists():
                        raise _PatchError(f"file to delete does not exist: {op.path}")
                    if pending_content is None and not source.is_file():
                        raise _PatchError(f"path to delete is not a file: {op.path}")
                    deleted_lines = 0
                    if pending_content is not None:
                        deleted_lines = _text_line_count(pending_content)
                    else:
                        raw = source.read_bytes()
                        try:
                            deleted_lines = _text_line_count(raw.decode("utf-8"))
                        except UnicodeDecodeError:
                            deleted_lines = 0
                    deletes.add(source)
                    writes.pop(source, None)
                    summaries.append(_PatchSummary(
                        action="delete",
                        path=op.path,
                        deleted=deleted_lines,
                    ))
                    continue

                pending_content = writes.get(source)
                if pending_content is None and not source.exists():
                    raise _PatchError(f"file to update does not exist: {op.path}")
                if pending_content is None and not source.is_file():
                    raise _PatchError(f"path to update is not a file: {op.path}")
                if pending_content is not None:
                    content = pending_content
                else:
                    raw = source.read_bytes()
                    try:
                        content = raw.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise _PatchError(f"file to update is not UTF-8 text: {op.path}") from exc
                uses_crlf = "\r\n" in content
                content = content.replace("\r\n", "\n")
                new_content = _apply_hunks(op.path, content, op.hunks or [])
                added, deleted = _line_diff_stats(content, new_content)
                if uses_crlf:
                    new_content = new_content.replace("\n", "\r\n")

                target = self._resolve(op.new_path) if op.new_path else source
                if op.new_path and (target.exists() or target in writes) and target != source:
                    raise _PatchError(f"move target already exists: {op.new_path}")
                writes[target] = new_content
                deletes.discard(target)
                if target != source:
                    deletes.add(source)
                    writes.pop(source, None)
                summaries.append(_PatchSummary(
                    action="move" if op.new_path else "update",
                    path=op.path,
                    new_path=op.new_path,
                    added=added,
                    deleted=deleted,
                ))

            if dry_run:
                return (
                    "Patch dry-run succeeded:\n"
                    + "\n".join(_format_summary(summary) for summary in summaries)
                )

            backups: dict[Path, bytes | None] = {}
            for path in set(writes) | deletes:
                backups[path] = path.read_bytes() if path.exists() else None

            try:
                for path in deletes:
                    if path.exists():
                        path.unlink()
                for path, content in writes.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8", newline="")
            except Exception:
                for path, data in backups.items():
                    if data is None:
                        if path.exists():
                            path.unlink()
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                raise

            for path in set(writes) | deletes:
                self._file_states.record_write(path)
            return (
                "Patch applied:\n"
                + "\n".join(_format_summary(summary) for summary in summaries)
            )
        except PermissionError as exc:
            return f"Error: {exc}"
        except _PatchError as exc:
            return f"Error applying patch: {exc}"
        except Exception as exc:
            return f"Error applying patch: {exc}"
