from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from rapidfuzz.distance import Indel, Opcode, Opcodes

from nanobot.execution.files import FileSnapshot, WritableFile

_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
_MAX_DIFF_LINES = 500
_MAX_DIFF_LINE_CHARS = 1200
_DIFF_CONTEXT_LINES = 3


@runtime_checkable
class FileEditSource(Protocol):
    """A tool that exposes its authorized mutation targets for activity snapshots."""

    def file_edit_targets(self, params: Mapping[str, object]) -> Iterable[WritableFile]: ...

    @property
    def file_edit_workspace(self) -> Path | None: ...


@dataclass(slots=True)
class FileEditTracker:
    call_id: str
    tool: str
    target: WritableFile
    display_path: str
    before: FileSnapshot

    @property
    def path(self) -> Path:
        return self.target.path


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

    def _hunk_lines(self, group: list[Opcode]) -> Iterator[str]:
        for code in group:
            if code.tag != "insert":
                marker = " " if code.tag == "equal" else "-"
                yield from (
                    marker + self.before_lines[index]
                    for index in range(code.src_start, code.src_end)
                )
            if code.tag in ("replace", "insert"):
                yield from (
                    "+" + self.after_lines[index]
                    for index in range(code.dest_start, code.dest_end)
                )


    def unified_payload(
        self, fromfile: str, tofile: str, *, context_lines: int, max_lines: int, max_line_chars: int,
    ) -> dict[str, Any] | None:
        remaining = max(0, int(max_lines))
        line_width = max(0, int(max_line_chars))
        lines = [f"--- {fromfile}", f"+++ {tofile}"]
        truncated = False
        for group in self._groups(max(0, int(context_lines))):
            if not remaining:
                truncated = True
                break
            body = list(islice(self._hunk_lines(group), remaining + 1))
            if len(body) > remaining:
                body.pop()
                truncated = True
            first, last = group[0], group[-1]
            # Clipping changes the displayed line counts, not the original hunk starts.
            old_start = first.src_start + (last.src_end > first.src_start)
            new_start = first.dest_start + (last.dest_end > first.dest_start)
            old_range = _format_hunk_range(old_start, sum(line[0] != "+" for line in body))
            new_range = _format_hunk_range(new_start, sum(line[0] != "-" for line in body))
            lines.append(f"@@ -{old_range} +{new_range} @@")
            for line in body:
                if line_width and len(line) > line_width + 1:
                    line = line[:line_width + 1]  # The diff marker is not part of the content.
                    truncated = True
                lines.append(line)
            remaining -= len(body)

        if len(lines) == 2:
            return None
        return {
            "format": "unified",
            "context": context_lines,
            "truncated": truncated,
            "text": "\n".join(lines),
        }


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


def display_file_edit_path(path: Path, workspace: Path | None) -> str:
    if workspace is not None:
        try:
            return path.resolve().relative_to(workspace.resolve()).as_posix()
        except Exception:
            pass
    return path.as_posix()


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
    return diff.unified_payload(
        fromfile, tofile, context_lines=context_lines, max_lines=max_lines,
        max_line_chars=max_line_chars,
    )


def _format_hunk_range(start: int, line_count: int) -> str:
    return str(start) if line_count == 1 else f"{start},{line_count}"


def prepare_file_edit_trackers(
    *,
    call_id: str,
    tool_name: str,
    tool: object,
    workspace: Path | None,
    params: object,
) -> list[FileEditTracker]:
    if not isinstance(params, dict) or not isinstance(tool, FileEditSource):
        return []
    display_workspace = tool.file_edit_workspace or workspace
    trackers: list[FileEditTracker] = []
    seen: set[Path] = set()
    for target in tool.file_edit_targets(cast(dict[str, object], params)):
        if target.path in seen:
            continue
        seen.add(target.path)
        trackers.append(FileEditTracker(
            call_id=str(call_id or ""),
            tool=tool_name,
            target=target,
            display_path=display_file_edit_path(target.path, display_workspace),
            before=target.snapshot(_MAX_SNAPSHOT_BYTES),
        ))
    return trackers


def build_file_edit_start_event(tracker: FileEditTracker) -> dict[str, Any]:
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
    *,
    diff: FileDiff | None = None,
) -> dict[str, Any]:
    after = tracker.target.snapshot(_MAX_SNAPSHOT_BYTES)
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
        operation=(
            "delete" if tracker.before.exists and not after.exists
            else "create" if not tracker.before.exists and after.exists
            else None
        ),
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
