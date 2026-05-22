"""File-edit activity helpers for WebUI progress events."""

from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

TRACKED_FILE_EDIT_TOOLS = frozenset({"write_file", "edit_file", "apply_patch"})
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
_LIVE_EMIT_INTERVAL_S = 0.18
_LIVE_EMIT_LINE_STEP = 24


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
    if before == "":
        return _text_line_count(after), 0
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


def _text_line_count(text: str) -> int:
    if not text:
        return 0
    line_count = 0
    last_was_newline = False
    last_was_cr = False
    for ch in text:
        if ch == "\r":
            line_count += 1
            last_was_newline = True
            last_was_cr = True
        elif ch == "\n":
            if not last_was_cr:
                line_count += 1
            last_was_newline = True
            last_was_cr = False
        else:
            last_was_newline = False
            last_was_cr = False
    return line_count if last_was_newline else line_count + 1


def prepare_file_edit_tracker(
    *,
    call_id: str,
    tool_name: str,
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> FileEditTracker | None:
    trackers = prepare_file_edit_trackers(
        call_id=call_id,
        tool_name=tool_name,
        tool=tool,
        workspace=workspace,
        params=params,
    )
    return trackers[0] if trackers else None


def prepare_file_edit_trackers(
    *,
    call_id: str,
    tool_name: str,
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> list[FileEditTracker]:
    if not is_file_edit_tool(tool_name):
        return []
    paths = resolve_file_edit_paths(tool_name, tool, workspace, params)
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
            display_path=display_file_edit_path(path, workspace),
            before=before,
        ))
    return trackers


def resolve_file_edit_paths(
    tool_name: str,
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> list[Path]:
    if tool_name == "apply_patch":
        return _resolve_apply_patch_paths(tool, workspace, params)
    path = resolve_file_edit_path(tool, workspace, params)
    if path is None:
        return []
    return [path]


def _resolve_apply_patch_paths(
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> list[Path]:
    if not isinstance(params, dict):
        return []
    edits = params.get("edits")
    if not isinstance(edits, list) or not edits:
        return []
    if params.get("dry_run") is True:
        return []

    resolved: list[Path] = []
    seen: set[Path] = set()
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        raw_path = edit.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        path = _resolve_raw_file_edit_path(tool, workspace, raw_path)
        if path is not None and path not in seen:
            seen.add(path)
            resolved.append(path)
    return resolved


def _resolve_raw_file_edit_path(
    tool: Any,
    workspace: Path | None,
    raw_path: str,
) -> Path | None:
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


def build_file_edit_end_event(
    tracker: FileEditTracker,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    after = read_file_snapshot(tracker.path)
    counted = False
    if tracker.before.countable and after.countable:
        added, deleted = line_diff_stats(tracker.before.text, after.text)
        counted = True
    else:
        predicted_after = _predict_after_text(tracker.tool, params or {}, tracker.before)
        if tracker.before.countable and predicted_after is not None:
            added, deleted = line_diff_stats(tracker.before.text, predicted_after)
            counted = True
        else:
            added, deleted = 0, 0
    return _event_payload(
        tracker,
        phase="end",
        status="done",
        added=added,
        deleted=deleted,
        approximate=False,
        binary=(after.binary or after.oversized or after.unreadable) and not counted,
    )


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


def build_file_edit_live_event(
    tracker: FileEditTracker,
    *,
    added: int,
    deleted: int = 0,
) -> dict[str, Any]:
    """Build an approximate in-progress event while tool-call arguments stream."""
    return _event_payload(
        tracker,
        phase="start",
        status="editing",
        added=added,
        deleted=deleted,
        approximate=True,
    )


def build_file_edit_pending_event(
    *,
    call_id: str,
    tool_name: str,
    added: int = 0,
    deleted: int = 0,
) -> dict[str, Any]:
    """Build an early placeholder before the streamed JSON path is available."""
    return {
        "version": 1,
        "call_id": str(call_id or ""),
        "tool": tool_name,
        "path": "",
        "phase": "start",
        "added": max(0, int(added)),
        "deleted": max(0, int(deleted)),
        "approximate": True,
        "status": "editing",
        "pending": True,
    }


class StreamingFileEditTracker:
    """Track file-edit tool arguments while the model is still streaming them.

    Tool execution events only begin after the provider has completed the full
    function call.  For large ``write_file`` calls, the long wait is usually the
    model producing the JSON ``content`` argument.  Large ``edit_file`` calls
    can have the same wait while ``old_text`` / ``new_text`` stream in.  This
    tracker converts those argument deltas into approximate WebUI file-edit
    events before the final exact diff is available.
    """

    def __init__(
        self,
        *,
        workspace: Path | None,
        tools: Any,
        emit: Callable[[list[dict[str, Any]]], Awaitable[None]],
    ) -> None:
        self._workspace = workspace
        self._tools = tools
        self._emit = emit
        self._states: dict[str, _StreamingFileEditState] = {}

    async def update(self, payload: dict[str, Any]) -> None:
        key = _stream_key(payload)
        if not key:
            return
        state = self._states.get(key)
        if state is None:
            state = _StreamingFileEditState(key=key)
            self._states[key] = state

        state.apply_delta(payload)
        if state.name == "apply_patch":
            await self._update_apply_patch(state)
            return
        if state.name not in {"write_file", "edit_file"}:
            return
        if state.path is None:
            state.path = _extract_complete_json_string(state.arguments, "path")
        if state.path is None:
            added, deleted = state.live_diff_counts()
            now = time.monotonic()
            if state.should_emit_pending(added, deleted, now):
                state.mark_pending_emitted(added, deleted, now)
                await self._emit([build_file_edit_pending_event(
                    call_id=state.call_id or state.key,
                    tool_name=state.name,
                    added=added,
                    deleted=deleted,
                )])
            return
        if state.tracker is None:
            tool = self._tools.get(state.name) if hasattr(self._tools, "get") else None
            state.tracker = prepare_file_edit_tracker(
                call_id=state.call_id or state.key,
                tool_name=state.name,
                tool=tool,
                workspace=self._workspace,
                params={"path": state.path},
            )
            if state.tracker is None:
                return

        added, deleted = state.live_diff_counts()
        now = time.monotonic()
        if not state.should_emit(added, deleted, now):
            return
        state.mark_emitted(added, deleted, now)
        await self._emit([build_file_edit_live_event(
            state.tracker,
            added=added,
            deleted=deleted,
        )])

    async def _update_apply_patch(self, state: _StreamingFileEditState) -> None:
        if _json_bool_true(state.arguments, "dry_run"):
            return
        tool = self._tools.get("apply_patch") if hasattr(self._tools, "get") else None
        events: list[dict[str, Any]] = []
        now = time.monotonic()

        path_matches = list(re.finditer(r'"path"\s*:\s*"([^"]+)"', state.arguments))
        if not path_matches:
            return

        for i, m in enumerate(path_matches):
            raw_path = m.group(1)
            path = _resolve_raw_file_edit_path(tool, self._workspace, raw_path)
            if path is None:
                continue

            segment_start = m.start()
            segment_end = path_matches[i + 1].start() if i + 1 < len(path_matches) else len(state.arguments)
            segment = state.arguments[segment_start:segment_end]

            action_match = re.search(r'"action"\s*:\s*"(replace|add|delete)"', segment)
            action = action_match.group(1) if action_match else "replace"

            old_text = _extract_json_string_prefix(segment, "old_text") or ""
            new_text = _extract_json_string_prefix(segment, "new_text") or ""

            added = _text_line_count(new_text) if action in ("replace", "add") else 0
            deleted = _text_line_count(old_text) if action in ("replace", "delete") else 0
            delete_file = action == "delete"

            file_state = state.patch_files.get(raw_path)
            if file_state is None:
                tracker = FileEditTracker(
                    call_id=state.call_id or state.key,
                    tool="apply_patch",
                    path=path,
                    display_path=display_file_edit_path(path, self._workspace),
                    before=read_file_snapshot(path),
                )
                file_state = _StreamingPatchFileState(tracker=tracker)
                state.patch_files[raw_path] = file_state
            if delete_file and added == 0 and deleted == 0 and file_state.tracker.before.countable:
                deleted = _text_line_count(file_state.tracker.before.text or "")
            if not file_state.should_emit(added, deleted, now):
                continue
            file_state.mark_emitted(added, deleted, now)
            events.append(build_file_edit_live_event(
                file_state.tracker,
                added=added,
                deleted=deleted,
            ))
        if events:
            await self._emit(events)

    async def flush(self) -> None:
        events: list[dict[str, Any]] = []
        now = time.monotonic()
        for state in self._states.values():
            for file_state in state.patch_files.values():
                added, deleted = file_state.last_added, file_state.last_deleted
                if not file_state.emitted_once:
                    continue
                if (
                    file_state.last_emitted_added == added
                    and file_state.last_emitted_deleted == deleted
                ):
                    continue
                file_state.mark_emitted(added, deleted, now)
                events.append(build_file_edit_live_event(
                    file_state.tracker,
                    added=added,
                    deleted=deleted,
                ))
            if state.tracker is None:
                continue
            added, deleted = state.live_diff_counts()
            if (
                state.last_emitted_added == added
                and state.last_emitted_deleted == deleted
                and state.emitted_once
            ):
                continue
            state.mark_emitted(added, deleted, now)
            events.append(build_file_edit_live_event(
                state.tracker,
                added=added,
                deleted=deleted,
            ))
        if events:
            await self._emit(events)

    def apply_final_call_ids(self, final_tool_calls: list[Any]) -> None:
        """Keep final start/end events keyed to any earlier streamed placeholder."""
        used_canonicals: set[str] = set()
        for tool_call in final_tool_calls:
            canonical = self.canonical_call_id_for(tool_call)
            if canonical and canonical not in used_canonicals:
                try:
                    tool_call.id = canonical
                    used_canonicals.add(canonical)
                except (AttributeError, TypeError):
                    pass

    def canonical_call_id_for(self, tool_call: Any) -> str | None:
        for state in self._states.values():
            if state.matches_final_tool_call(tool_call):
                return state.call_id or (state.tracker.call_id if state.tracker else None) or state.key
        return None

    async def error_unmatched(
        self,
        final_tool_calls: list[Any],
        error: str,
    ) -> None:
        """Mark streamed edits as failed when no final tool call will run."""
        events: list[dict[str, Any]] = []
        for state in self._states.values():
            for file_state in state.patch_files.values():
                if any(state.matches_final_tool_call(tool_call) for tool_call in final_tool_calls):
                    continue
                events.append(build_file_edit_error_event(file_state.tracker, error))
            if state.tracker is None:
                continue
            if any(state.matches_final_tool_call(tool_call) for tool_call in final_tool_calls):
                continue
            events.append(build_file_edit_error_event(state.tracker, error))
        if events:
            await self._emit(events)


@dataclass(slots=True)
class _StreamingJsonStringField:
    key: str
    scan_pos: int | None = None
    closed: bool = False
    escape: bool = False
    unicode_remaining: int = 0
    unicode_buffer: str = ""
    newline_count: int = 0
    has_chars: bool = False
    last_char_newline: bool = False
    last_char_cr: bool = False

    @property
    def line_count(self) -> int:
        if not self.has_chars:
            return 0
        return self.newline_count + (0 if self.last_char_newline else 1)

    def reset(self) -> None:
        self.scan_pos = None
        self.closed = False
        self.escape = False
        self.unicode_remaining = 0
        self.unicode_buffer = ""
        self.newline_count = 0
        self.has_chars = False
        self.last_char_newline = False
        self.last_char_cr = False

    def scan(self, source: str) -> None:
        if self.closed:
            return
        if self.scan_pos is None:
            match = re.search(rf'"{re.escape(self.key)}"\s*:\s*"', source)
            if match is None:
                return
            self.scan_pos = match.end()
        i = self.scan_pos
        while i < len(source):
            ch = source[i]
            if self.unicode_remaining > 0:
                self.unicode_buffer += ch
                self.unicode_remaining -= 1
                if self.unicode_remaining == 0:
                    try:
                        decoded = chr(int(self.unicode_buffer, 16))
                    except ValueError:
                        decoded = "x"
                    self.unicode_buffer = ""
                    self._mark_char(decoded)
                i += 1
                continue
            if self.escape:
                self.escape = False
                if ch == "u":
                    self.unicode_remaining = 4
                    self.unicode_buffer = ""
                elif ch == "n":
                    self._mark_char("\n")
                elif ch == "r":
                    self._mark_char("\r")
                else:
                    self._mark_char(ch)
                i += 1
                continue
            if ch == "\\":
                self.escape = True
                i += 1
                continue
            if ch == '"':
                self.closed = True
                i += 1
                break
            self._mark_char(ch)
            i += 1
        self.scan_pos = i

    def _mark_char(self, ch: str) -> None:
        self.has_chars = True
        if ch == "\r":
            self.newline_count += 1
            self.last_char_newline = True
            self.last_char_cr = True
        elif ch == "\n":
            if not self.last_char_cr:
                self.newline_count += 1
            self.last_char_newline = True
            self.last_char_cr = False
        else:
            self.last_char_newline = False
            self.last_char_cr = False


@dataclass(slots=True)
class _StreamingPatchFileState:
    tracker: FileEditTracker
    emitted_once: bool = False
    last_emitted_added: int = -1
    last_emitted_deleted: int = -1
    last_emit_at: float = 0.0
    last_added: int = 0
    last_deleted: int = 0

    def should_emit(self, added: int, deleted: int, now: float) -> bool:
        self.last_added = added
        self.last_deleted = deleted
        if not self.emitted_once:
            return True
        if added == self.last_emitted_added and deleted == self.last_emitted_deleted:
            return False
        if max(
            abs(added - self.last_emitted_added),
            abs(deleted - self.last_emitted_deleted),
        ) >= _LIVE_EMIT_LINE_STEP:
            return True
        return now - self.last_emit_at >= _LIVE_EMIT_INTERVAL_S

    def mark_emitted(self, added: int, deleted: int, now: float) -> None:
        self.emitted_once = True
        self.last_added = added
        self.last_deleted = deleted
        self.last_emitted_added = added
        self.last_emitted_deleted = deleted
        self.last_emit_at = now


@dataclass(slots=True)
class _StreamingFileEditState:
    key: str
    call_id: str = ""
    name: str = ""
    arguments: str = ""
    path: str | None = None
    tracker: FileEditTracker | None = None
    content: _StreamingJsonStringField = field(
        default_factory=lambda: _StreamingJsonStringField("content")
    )
    old_text: _StreamingJsonStringField = field(
        default_factory=lambda: _StreamingJsonStringField("old_text")
    )
    new_text: _StreamingJsonStringField = field(
        default_factory=lambda: _StreamingJsonStringField("new_text")
    )
    patch_files: dict[str, _StreamingPatchFileState] = field(default_factory=dict)
    emitted_once: bool = False
    last_emitted_added: int = -1
    last_emitted_deleted: int = -1
    last_emit_at: float = 0.0
    pending_emitted: bool = False
    last_pending_added: int = -1
    last_pending_deleted: int = -1
    last_pending_at: float = 0.0

    def apply_delta(self, payload: dict[str, Any]) -> None:
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            self.call_id = call_id
        name = payload.get("name")
        if isinstance(name, str) and name:
            self.name = name
        args = payload.get("arguments")
        if isinstance(args, str):
            self.arguments = args
            self.content.reset()
            self.old_text.reset()
            self.new_text.reset()
            self.patch_files.clear()
            return
        delta = payload.get("arguments_delta")
        if isinstance(delta, str) and delta:
            self.arguments += delta

    def live_diff_counts(self) -> tuple[int, int]:
        if self.name == "write_file":
            self.content.scan(self.arguments)
            return self.content.line_count, 0
        if self.name == "edit_file":
            self.old_text.scan(self.arguments)
            self.new_text.scan(self.arguments)
            return self.new_text.line_count, self.old_text.line_count
        return 0, 0

    def should_emit(self, added: int, deleted: int, now: float) -> bool:
        if not self.emitted_once:
            return True
        if added == self.last_emitted_added and deleted == self.last_emitted_deleted:
            return False
        if max(
            abs(added - self.last_emitted_added),
            abs(deleted - self.last_emitted_deleted),
        ) >= _LIVE_EMIT_LINE_STEP:
            return True
        return now - self.last_emit_at >= _LIVE_EMIT_INTERVAL_S

    def mark_emitted(self, added: int, deleted: int, now: float) -> None:
        self.emitted_once = True
        self.last_emitted_added = added
        self.last_emitted_deleted = deleted
        self.last_emit_at = now

    def should_emit_pending(self, added: int, deleted: int, now: float) -> bool:
        if not self.pending_emitted:
            return True
        if added == self.last_pending_added and deleted == self.last_pending_deleted:
            return False
        if max(
            abs(added - self.last_pending_added),
            abs(deleted - self.last_pending_deleted),
        ) >= _LIVE_EMIT_LINE_STEP:
            return True
        return now - self.last_pending_at >= _LIVE_EMIT_INTERVAL_S

    def mark_pending_emitted(self, added: int, deleted: int, now: float) -> None:
        self.pending_emitted = True
        self.last_pending_added = added
        self.last_pending_deleted = deleted
        self.last_pending_at = now

    def matches_final_tool_call(self, tool_call: Any) -> bool:
        call_id = getattr(tool_call, "id", None)
        canonical = self.call_id or (self.tracker.call_id if self.tracker else "")
        if isinstance(call_id, str) and call_id and canonical and call_id == canonical:
            return True
        name = getattr(tool_call, "name", None)
        if name != self.name:
            return False
        if self.name == "apply_patch":
            arguments = getattr(tool_call, "arguments", None)
            if not isinstance(arguments, dict):
                return False
            edits = arguments.get("edits")
            if not isinstance(edits, list):
                return False
            return '"edits"' in self.arguments
        arguments = getattr(tool_call, "arguments", None)
        if not isinstance(arguments, dict):
            return False
        path = arguments.get("path")
        if self.path is None and isinstance(path, str) and path:
            self.path = path
            return True
        return isinstance(path, str) and path == self.path


def _stream_key(payload: dict[str, Any]) -> str:
    index = payload.get("index")
    if isinstance(index, int):
        return f"idx:{index}"
    if isinstance(index, str) and index:
        return f"idx:{index}"
    call_id = payload.get("call_id")
    if isinstance(call_id, str) and call_id:
        return f"id:{call_id}"
    return ""


def _json_bool_true(source: str, key: str) -> bool:
    return re.search(rf'"{re.escape(key)}"\s*:\s*true\b', source) is not None


def _extract_json_string_prefix(source: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"', source)
    if match is None:
        return None
    out: list[str] = []
    i = match.end()
    escape = False
    while i < len(source):
        ch = source[i]
        if escape:
            escape = False
            if ch == "n":
                out.append("\n")
            elif ch == "r":
                out.append("\r")
            elif ch == "t":
                out.append("\t")
            elif ch == "u":
                digits = source[i + 1:i + 5]
                if len(digits) < 4:
                    break
                try:
                    out.append(chr(int(digits, 16)))
                except ValueError:
                    break
                i += 4
            else:
                out.append(ch)
            i += 1
            continue
        if ch == "\\":
            escape = True
            i += 1
            continue
        if ch == '"':
            return "".join(out)
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_complete_json_string(source: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"', source)
    if match is None:
        return None
    out: list[str] = []
    i = match.end()
    escape = False
    while i < len(source):
        ch = source[i]
        if escape:
            escape = False
            if ch == "n":
                out.append("\n")
            elif ch == "r":
                out.append("\r")
            elif ch == "t":
                out.append("\t")
            elif ch == "u":
                digits = source[i + 1:i + 5]
                if len(digits) < 4:
                    return None
                try:
                    out.append(chr(int(digits, 16)))
                except ValueError:
                    return None
                i += 4
            else:
                out.append(ch)
            i += 1
            continue
        if ch == "\\":
            escape = True
            i += 1
            continue
        if ch == '"':
            return "".join(out)
        out.append(ch)
        i += 1
    return None


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
        "absolute_path": tracker.path.as_posix(),
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
    return None
