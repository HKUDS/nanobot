"""Format structured agent activity for terminal surfaces."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from rich.markup import escape

_MAX_ARG_CHARS = 120
_MAX_RESULT_CHARS = 160
_MAX_DETAIL_ITEMS = 4


def format_activity_rows(
    metadata: Mapping[str, Any] | None,
    *,
    include_start: bool = True,
) -> list[str]:
    """Return stable terminal rows for structured progress metadata.

    When ``include_start`` is False, in-progress (start-phase) events are
    skipped: surfaces that show a live status indicator only need the
    completed/failed line plus its results, collapsing the previous
    "Reading…" + "Read" two-line rendering into one.
    """
    if not isinstance(metadata, Mapping):
        return []
    rows: list[str] = []
    rows.extend(
        format_tool_event(event)
        for event in _dicts(metadata.get("_tool_events"))
        if include_start or str(event.get("phase") or "").lower() != "start"
    )
    rows.extend(
        format_file_edit_event(event)
        for event in _dicts(metadata.get("_file_edit_events"))
        if include_start or str(event.get("phase") or "").lower() != "start"
    )
    return [row for row in rows if row]


def current_activity_name(metadata: Mapping[str, Any] | None) -> str:
    """Return the active start-phase activity name, if any."""
    if not isinstance(metadata, Mapping):
        return ""
    for event in reversed(list(_dicts(metadata.get("_tool_events")))):
        if str(event.get("phase") or "").lower() == "start":
            return str(event.get("name") or event.get("tool") or "tool")
    for event in reversed(list(_dicts(metadata.get("_file_edit_events")))):
        if str(event.get("phase") or "").lower() == "start":
            return "file edit"
    return ""


def format_tool_event(event: Mapping[str, Any]) -> str:
    phase = str(event.get("phase") or "").lower()
    name = str(event.get("name") or event.get("tool") or "tool")
    verb = _tool_verb(name, phase)
    icon, style = _phase_marker(phase)
    detail = _tool_detail(name, event)
    target = detail or name
    if phase == "start":
        return f"[{style}]{icon} {escape(verb)} {escape(target)}[/{style}]"

    if phase == "error":
        error = _truncate(str(event.get("error") or event.get("detail") or ""), _MAX_RESULT_CHARS)
        tail = f" [red]— {escape(error)}[/red]" if error else ""
        return f"[{style}]{icon} {escape(verb)}[/{style}] {escape(target)}{tail}"

    summary = _result_summary(name, event.get("result"))
    tail = f" [dim]— {escape(summary)}[/dim]" if summary else ""
    return f"[{style}]{icon} {escape(verb)}[/{style}] {escape(target)}{tail}"


def format_file_edit_event(event: Mapping[str, Any]) -> str:
    phase = str(event.get("phase") or "").lower()
    verb = {"start": "Editing", "end": "Edited", "error": "Edit failed"}.get(
        phase,
        phase.title() or "Edit",
    )
    icon, style = _phase_marker(phase)
    path = str(event.get("path") or "(pending path)")
    added = _int(event.get("added"))
    deleted = _int(event.get("deleted"))
    stats = f" +{added} -{deleted}" if added or deleted else ""
    detail = stats.strip() or "pending"
    if event.get("approximate"):
        detail = f"{detail} approx"
    if event.get("operation") == "delete":
        detail = f"{detail} deleted"
    error = _truncate(str(event.get("error") or ""), _MAX_RESULT_CHARS)
    if error:
        return f"[{style}]{icon} {escape(verb)}[/{style}] {escape(path)} [red]— {escape(error)}[/red]"
    tail = f" [dim]— {escape(detail)}[/dim]" if detail else ""
    return f"[{style}]{icon} {escape(verb)}[/{style}] {escape(path)}{tail}"


def _tool_detail(name: str, event: Mapping[str, Any]) -> str:
    args = event.get("arguments")
    if not isinstance(args, Mapping):
        return ""
    if name in {"exec", "shell"}:
        command = args.get("command")
        if isinstance(command, str) and command.strip():
            return _truncate(command.strip(), _MAX_ARG_CHARS)
        return name
    if name in {"read_file", "write_file", "edit_file"}:
        path = args.get("path")
        return str(path) if isinstance(path, str) else ""
    if name == "list_dir":
        path = args.get("path")
        return str(path) if isinstance(path, str) else "."
    return _truncate(_json(args), _MAX_ARG_CHARS)


def _tool_verb(name: str, phase: str) -> str:
    if phase == "start":
        return {
            "exec": "Running",
            "shell": "Running",
            "list_dir": "Exploring",
            "read_file": "Reading",
            "write_file": "Writing",
            "edit_file": "Editing",
            "apply_patch": "Patching",
        }.get(name, "Using")
    if phase == "error":
        return {
            "exec": "Failed",
            "shell": "Failed",
            "list_dir": "Explore failed",
            "read_file": "Read failed",
            "write_file": "Write failed",
            "edit_file": "Edit failed",
            "apply_patch": "Patch failed",
        }.get(name, "Failed")
    return {
        "exec": "Ran",
        "shell": "Ran",
        "list_dir": "Explored",
        "read_file": "Read",
        "write_file": "Wrote",
        "edit_file": "Edited",
        "apply_patch": "Patched",
    }.get(name, "Used")


def _phase_marker(phase: str) -> tuple[str, str]:
    if phase == "end":
        return "✓", "green"
    if phase == "error":
        return "✕", "red"
    return "·", "bright_black"


def _result_summary(name: str, result: Any) -> str:
    if result is None:
        return ""
    if name == "list_dir" and isinstance(result, str):
        return _list_dir_summary(result)
    if isinstance(result, str):
        summary = _truncate(" ".join(result.split()), _MAX_RESULT_CHARS)
        return summary
    if isinstance(result, Mapping):
        for key in ("summary", "message", "error", "output", "stdout"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return _truncate(" ".join(value.split()), _MAX_RESULT_CHARS)
        if "exit_code" in result:
            return f"exit={result.get('exit_code')}"
    summary = _truncate(_json(result), _MAX_RESULT_CHARS)
    return summary


def _list_dir_summary(result: str) -> str:
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    if not lines:
        return ""
    visible = [line for line in lines if not line.startswith("(")]
    if not visible:
        return _truncate(" ".join(lines), _MAX_RESULT_CHARS)
    names = [_strip_file_icon(line) for line in visible[:_MAX_DETAIL_ITEMS]]
    more = len(visible) - len(names)
    suffix = f", +{more} more" if more > 0 else ""
    return f"{len(visible)} entries: {', '.join(names)}{suffix}"


def _strip_file_icon(value: str) -> str:
    for prefix in ("📁 ", "📄 "):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def _dicts(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
