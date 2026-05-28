"""Sanitize session messages before L0 capture (strip injections, keep user evidence)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from nanobot.utils.helpers import stringify_text_blocks

# Keep in sync with ``ContextBuilder._RUNTIME_CONTEXT_*`` (avoid importing context → runner cycle).
_RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
_RUNTIME_CONTEXT_END = "[/Runtime Context]"
_MESSAGE_TIME_PREFIX_RE = re.compile(r"^\[Message Time: [^\]]+\]\n?")
_TASK_CANVAS_MARKER = "[Task canvas]"
_CONTEXT_BUDGET_PREFIXES = ("[Context budget:", "[Context Budget:")
_MIN_CAPTURE_CHARS = 2
_PERSISTED_TOOL_MARKER = "[tool output persisted]"


@dataclass(frozen=True)
class L0CaptureRow:
    """One row ready for ``l0_messages`` insertion."""

    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    timestamp_ms: int = 0


def sanitize_turn_messages(messages: list[dict[str, Any]]) -> list[L0CaptureRow]:
    """Return sanitized L0 rows for a turn slice (may be shorter than input)."""
    rows: list[L0CaptureRow] = []
    for message in messages:
        row = sanitize_message(message)
        if row is not None:
            rows.append(row)
    return rows


def sanitize_message(message: dict[str, Any]) -> L0CaptureRow | None:
    """Normalize one OpenAI-style message for L0 storage, or ``None`` to skip."""
    role = message.get("role")
    if role not in ("user", "assistant", "tool"):
        return None

    timestamp_ms = _message_timestamp_ms(message)
    if role == "tool":
        return _sanitize_tool_message(message, timestamp_ms=timestamp_ms)
    if role == "user":
        content = _normalize_user_content(message.get("content"))
        if not _keepable_text(content):
            return None
        return L0CaptureRow(role="user", content=content, timestamp_ms=timestamp_ms)
    return _sanitize_assistant_message(message, timestamp_ms=timestamp_ms)


def _sanitize_tool_message(message: dict[str, Any], *, timestamp_ms: int) -> L0CaptureRow | None:
    name = message.get("name")
    tool_name = str(name) if name else None
    tool_call_id = message.get("tool_call_id")
    tid = str(tool_call_id) if tool_call_id else None
    content = _stringify_content(message.get("content"))
    if _PERSISTED_TOOL_MARKER in content:
        content = _compact_persisted_tool_content(content)
    content = _strip_injection_blocks(content)
    if not content.strip():
        return None
    return L0CaptureRow(
        role="tool",
        content=content,
        name=tool_name,
        tool_call_id=tid,
        timestamp_ms=timestamp_ms,
    )


def _sanitize_assistant_message(message: dict[str, Any], *, timestamp_ms: int) -> L0CaptureRow | None:
    content = _stringify_content(message.get("content"))
    content = _strip_injection_blocks(content)
    tool_calls = message.get("tool_calls")
    if not content.strip() and isinstance(tool_calls, list) and tool_calls:
        names: list[str] = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            func = tc.get("function")
            if isinstance(func, dict) and func.get("name"):
                names.append(str(func["name"]))
            elif tc.get("name"):
                names.append(str(tc["name"]))
        if names:
            content = f"[assistant tool_calls: {', '.join(names)}]"
    if not _keepable_text(content):
        return None
    return L0CaptureRow(role="assistant", content=content, timestamp_ms=timestamp_ms)


def _normalize_user_content(content: Any) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = stringify_text_blocks(content) or ""
    else:
        text = str(content) if content is not None else ""
    text = _MESSAGE_TIME_PREFIX_RE.sub("", text, count=1)
    tag = _RUNTIME_CONTEXT_TAG
    if tag in text:
        end = _RUNTIME_CONTEXT_END
        pos = text.find(tag)
        before = text[:pos].rstrip("\n ")
        after = ""
        end_pos = text.find(end, pos + len(tag)) if end else -1
        if end_pos >= 0:
            after = text[end_pos + len(end) :].strip()
        text = "\n".join(part for part in (before, after) if part).strip()
    return _strip_injection_blocks(text)


def _strip_injection_blocks(text: str) -> str:
    if not text:
        return ""
    if _TASK_CANVAS_MARKER in text:
        text = _strip_block(text, _TASK_CANVAS_MARKER, end_markers=("```", _RUNTIME_CONTEXT_END))
    for prefix in _CONTEXT_BUDGET_PREFIXES:
        if prefix in text:
            text = _strip_line_block(text, prefix)
    tag = _RUNTIME_CONTEXT_TAG
    if tag in text:
        end = _RUNTIME_CONTEXT_END
        start = text.find(tag)
        end_pos = text.find(end, start + len(tag)) if end else -1
        if end_pos >= 0:
            text = (text[:start] + text[end_pos + len(end) :]).strip()
        else:
            text = text[:start].strip()
    return text.strip()


def _strip_block(text: str, start_marker: str, *, end_markers: tuple[str, ...]) -> str:
    start = text.find(start_marker)
    if start < 0:
        return text
    end = len(text)
    for marker in end_markers:
        pos = text.find(marker, start + len(start_marker))
        if pos >= 0:
            close = text.find("\n", pos + len(marker))
            end = min(end, close if close >= 0 else len(text))
    return (text[:start] + text[end:]).strip()


def _strip_line_block(text: str, line_prefix: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.strip().startswith(line_prefix):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _compact_persisted_tool_content(content: str) -> str:
    """Keep persist reference lines without duplicating huge previews in L0."""
    keep: list[str] = []
    preview_lines = 0
    for line in content.splitlines():
        if line.startswith("Full output saved to:") or line.startswith("Original size:"):
            keep.append(line)
        elif line.startswith("node_id:"):
            keep.append(line)
        elif line.startswith("Preview:"):
            keep.append(line)
            preview_lines = 0
        elif preview_lines < 3 and line.strip():
            keep.append(line)
            preview_lines += 1
        elif line.startswith("...") and "truncated" in line.lower():
            keep.append(line)
            break
    if not keep:
        return _PERSISTED_TOOL_MARKER
    return "\n".join(keep)


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text = stringify_text_blocks(content)
        if text is not None:
            return text
        try:
            return json.dumps(content, ensure_ascii=False)
        except TypeError:
            return str(content)
    if content is None:
        return ""
    return str(content)


def _keepable_text(text: str) -> bool:
    return len(text.strip()) >= _MIN_CAPTURE_CHARS


def _message_timestamp_ms(message: dict[str, Any]) -> int:
    from datetime import datetime

    ts = message.get("timestamp")
    if isinstance(ts, str):
        try:
            return int(datetime.fromisoformat(ts).timestamp() * 1000)
        except ValueError:
            pass
    if isinstance(ts, (int, float)):
        value = float(ts)
        if value > 1e12:
            return int(value)
        return int(value * 1000)
    import time

    return int(time.time() * 1000)
