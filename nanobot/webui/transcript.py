"""Append-only WebUI display transcript (JSONL), separate from agent session."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlparse

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.session.manager import SessionManager

WEBUI_TRANSCRIPT_SCHEMA_VERSION = 3
_MAX_TRANSCRIPT_FILE_BYTES = 8 * 1024 * 1024
_MARKDOWN_LOCAL_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\((<[^>]+>|[^)\s]+)(\s+(?:\"[^\"]*\"|'[^']*'))?\)"
)
_INLINE_MARKDOWN_IMAGE_EXTS: frozenset[str] = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
})
_INLINE_MARKDOWN_VIDEO_EXTS: frozenset[str] = frozenset({
    ".mp4",
    ".mov",
    ".webm",
})
_INLINE_MARKDOWN_MEDIA_EXTS = _INLINE_MARKDOWN_IMAGE_EXTS | _INLINE_MARKDOWN_VIDEO_EXTS
_FILE_EDIT_TOOL_NAMES: frozenset[str] = frozenset({
    "write_file",
    "edit_file",
    "apply_patch",
})
_TURN_DISPLAY_EVENTS: frozenset[str] = frozenset({
    "reasoning_delta",
    "reasoning_end",
    "delta",
    "stream_end",
    "message",
    "file_edit",
    "turn_end",
})


def rewrite_local_markdown_images(
    text: str,
    *,
    workspace_path: Path,
    sign_path: Callable[[Path], Mapping[str, Any] | None],
) -> str:
    """Rewrite markdown media paths inside the workspace to signed WebUI media URLs."""
    if "![" not in text:
        return text

    def resolve_url(raw_url: str) -> str | None:
        url = raw_url.strip()
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1].strip()
        if not url or url.startswith(("/api/media/", "#")):
            return None
        parsed = urlparse(url)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            return None
        path_text = unquote(url)
        if Path(path_text).suffix.lower() not in _INLINE_MARKDOWN_MEDIA_EXTS:
            return None
        candidate = Path(path_text).expanduser()
        if not candidate.is_absolute():
            candidate = workspace_path / candidate
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(workspace_path)
        except (OSError, ValueError):
            return None
        if not resolved.is_file():
            return None
        signed = sign_path(resolved)
        return str(signed.get("url")) if signed and signed.get("url") else None

    def replace(match: re.Match[str]) -> str:
        signed_url = resolve_url(match.group(2))
        if not signed_url:
            return match.group(0)
        title = match.group(3) or ""
        return f"![{match.group(1)}]({signed_url}{title})"

    return _MARKDOWN_LOCAL_IMAGE_RE.sub(replace, text)


def _media_kind_from_name(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in _INLINE_MARKDOWN_IMAGE_EXTS:
        return "image"
    if ext in _INLINE_MARKDOWN_VIDEO_EXTS:
        return "video"
    return "file"


def webui_transcript_path(session_key: str) -> Path:
    stem = SessionManager.safe_key(session_key)
    return get_webui_dir() / f"{stem}.jsonl"


def read_transcript_lines(session_key: str) -> list[dict[str, Any]]:
    path = webui_transcript_path(session_key)
    if not path.is_file():
        return []
    size = path.stat().st_size
    if size > _MAX_TRANSCRIPT_FILE_BYTES:
        logger.warning("webui transcript too large, skipping: {}", path)
        return []
    lines_out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("bad jsonl at {} line {}", path, line_no)
                    continue
                if isinstance(obj, dict):
                    lines_out.append(obj)
    except OSError as e:
        logger.warning("read transcript failed {}: {}", path, e)
        return []
    return lines_out


def append_transcript_object(session_key: str, obj: dict[str, Any]) -> None:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > _MAX_TRANSCRIPT_FILE_BYTES:
        msg = "webui transcript line too large"
        raise ValueError(msg)
    path = webui_transcript_path(session_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = raw + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def delete_webui_transcript(session_key: str) -> bool:
    path = webui_transcript_path(session_key)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError as e:
        logger.warning("Failed to delete webui transcript {}: {}", path, e)
        return False


def build_user_transcript_event(
    chat_id: str,
    text: str,
    *,
    media_paths: list[Any] | None = None,
    cli_apps: list[Any] | None = None,
    mcp_presets: list[Any] | None = None,
) -> dict[str, Any] | None:
    paths = [str(path) for path in (media_paths or []) if path]
    if not text and not paths:
        return None
    event: dict[str, Any] = {
        "event": "user",
        "chat_id": chat_id,
        "text": text,
    }
    if paths:
        event["media_paths"] = paths
    apps = [dict(app) for app in (cli_apps or []) if isinstance(app, Mapping)]
    if apps:
        event["cli_apps"] = apps
    presets = [dict(preset) for preset in (mcp_presets or []) if isinstance(preset, Mapping)]
    if presets:
        event["mcp_presets"] = presets
    return event


def _session_user_event(
    session_key: str,
    message: dict[str, Any],
) -> dict[str, Any] | None:
    if message.get("role") != "user":
        return None
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    media = message.get("media")
    cli_apps = message.get("cli_apps")
    mcp_presets = message.get("mcp_presets")
    chat_id = session_key.split(":", 1)[1] if ":" in session_key else session_key
    return build_user_transcript_event(
        chat_id,
        text,
        media_paths=media if isinstance(media, list) else None,
        cli_apps=cli_apps if isinstance(cli_apps, list) else None,
        mcp_presets=mcp_presets if isinstance(mcp_presets, list) else None,
    )


def _assistant_text_signature(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _session_backfill_turns(
    session_key: str,
    session_messages: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], tuple[str, ...]]]:
    turns: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    current_user: dict[str, Any] | None = None
    assistant_texts: list[str] = []

    def flush() -> None:
        if current_user is None:
            return
        signature = tuple(text for text in assistant_texts if text)
        if signature:
            turns.append((current_user, signature))

    for message in session_messages:
        role = message.get("role")
        if role == "user":
            flush()
            current_user = _session_user_event(session_key, message)
            assistant_texts = []
            continue
        if role == "assistant" and current_user is not None:
            text = _assistant_text_signature(message.get("content"))
            if text:
                assistant_texts.append(text)
    flush()
    return turns


def _split_transcript_turns(lines: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    turns: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for rec in lines:
        current.append(rec)
        if rec.get("event") == "turn_end":
            turns.append(current)
            current = []
    if current:
        turns.append(current)
    return turns


def _transcript_turn_signature(records: list[dict[str, Any]]) -> tuple[str, ...]:
    texts: list[str] = []
    for message in replay_transcript_to_ui_messages(records):
        if message.get("role") != "assistant" or message.get("kind") == "trace":
            continue
        text = _assistant_text_signature(message.get("content"))
        if text:
            texts.append(text)
    return tuple(texts)


def _find_unique_session_turn(
    session_turns: list[tuple[dict[str, Any], tuple[str, ...]]],
    signature: tuple[str, ...],
    start: int,
) -> int | None:
    if not signature:
        return None
    found: int | None = None
    for index in range(start, len(session_turns)):
        if session_turns[index][1] != signature:
            continue
        if found is not None:
            return None
        found = index
    return found


def _with_backfilled_user(
    records: list[dict[str, Any]],
    user_event: dict[str, Any],
) -> list[dict[str, Any]]:
    for index, rec in enumerate(records):
        if rec.get("event") in _TURN_DISPLAY_EVENTS:
            return [*records[:index], dict(user_event), *records[index:]]
    return records


def inject_missing_user_events_from_session(
    session_key: str,
    lines: list[dict[str, Any]],
    session_messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Backfill user rows for legacy WebUI transcripts that only stored assistant streams."""
    if not lines or not session_messages:
        return lines
    session_turns = _session_backfill_turns(session_key, session_messages)
    if not session_turns:
        return lines

    out: list[dict[str, Any]] = []
    session_cursor = 0
    for turn in _split_transcript_turns(lines):
        has_user = any(rec.get("event") == "user" for rec in turn)
        signature = _transcript_turn_signature(turn)
        match_index = _find_unique_session_turn(session_turns, signature, session_cursor)
        if match_index is None:
            out.extend(turn)
            continue
        out.extend(turn if has_user else _with_backfilled_user(turn, session_turns[match_index][0]))
        session_cursor = match_index + 1
    return out


def _format_tool_call_trace(call: Any) -> str | None:
    if not call or not isinstance(call, dict):
        return None
    fn = call.get("function")
    name = fn.get("name") if isinstance(fn, dict) else None
    if not isinstance(name, str) or not name:
        raw_name = call.get("name")
        name = raw_name if isinstance(raw_name, str) else ""
    if not name:
        return None
    args = (fn.get("arguments") if isinstance(fn, dict) else None) or call.get("arguments")
    if isinstance(args, str) and args.strip():
        return f"{name}({args})"
    if args and isinstance(args, dict):
        return f"{name}({json.dumps(args, ensure_ascii=False)})"
    return f"{name}()"


def tool_trace_lines_from_events(events: Any) -> list[str]:
    if not isinstance(events, list):
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for event in events:
        if not event or not isinstance(event, dict):
            continue
        if event.get("phase") not in {"start", "end", "error"}:
            continue
        call_id = event.get("call_id")
        if isinstance(call_id, str) and call_id:
            if call_id in seen:
                continue
            seen.add(call_id)
        t = _format_tool_call_trace(event)
        if t:
            lines.append(t)
    return lines


_PHASE_RANK = {"start": 1, "end": 2, "error": 3}


def _normalize_tool_events(events: Any) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []
    out: list[dict[str, Any]] = []
    for event in events:
        if not event or not isinstance(event, dict):
            continue
        if event.get("phase") not in {"start", "end", "error"}:
            continue
        if not isinstance(event.get("name"), str):
            fn = event.get("function")
            if not (isinstance(fn, dict) and isinstance(fn.get("name"), str)):
                continue
        out.append(dict(event))
    return out


def _tool_event_key(event: dict[str, Any]) -> str:
    call_id = event.get("call_id")
    if isinstance(call_id, str) and call_id:
        return f"call:{call_id}"
    return _format_tool_call_trace(event) or json.dumps(event, sort_keys=True, ensure_ascii=False)


def _tool_event_file_edit_key(event: dict[str, Any]) -> str | None:
    call_id = event.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        return None
    name = event.get("name")
    if not isinstance(name, str) or not name:
        fn = event.get("function")
        name = fn.get("name") if isinstance(fn, dict) else ""
    if not isinstance(name, str) or name not in _FILE_EDIT_TOOL_NAMES:
        return None
    return f"{call_id}|{name}"


def _merge_tool_events(previous: Any, incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(previous, list) or not previous:
        return incoming
    if not incoming:
        return [dict(event) for event in previous if isinstance(event, dict)]
    merged = [dict(event) for event in previous if isinstance(event, dict)]
    index_by_key = {_tool_event_key(event): idx for idx, event in enumerate(merged)}
    for event in incoming:
        key = _tool_event_key(event)
        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(merged)
            merged.append(event)
            continue
        existing = merged[existing_index]
        incoming_rank = _PHASE_RANK.get(str(event.get("phase")), 0)
        existing_rank = _PHASE_RANK.get(str(existing.get("phase")), 0)
        if incoming_rank >= existing_rank:
            merged[existing_index] = {**existing, **event}
    return merged


def _file_edit_key(edit: dict[str, Any]) -> str:
    call_id = str(edit.get("call_id") or "")
    tool = str(edit.get("tool") or "")
    if call_id:
        return f"{call_id}|{tool}"
    return f"{tool}|{edit.get('path') or ''}"


def _message_has_file_edit_for_tool_event(
    message: dict[str, Any],
    event: dict[str, Any],
) -> bool:
    key = _tool_event_file_edit_key(event)
    if not key:
        return False
    edits = message.get("fileEdits")
    if not isinstance(edits, list):
        return False
    return any(isinstance(edit, dict) and _file_edit_key(edit) == key for edit in edits)


def _filter_covered_file_edit_tool_events(
    messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not events:
        return events
    return [
        event
        for event in events
        if not any(_message_has_file_edit_for_tool_event(message, event) for message in messages)
    ]


def _strip_covered_file_edit_tool_hints(
    message: dict[str, Any],
    edits: list[dict[str, Any]],
) -> dict[str, Any]:
    incoming_keys = {
        _file_edit_key(edit)
        for edit in edits
        if isinstance(edit, dict)
    }
    events = message.get("toolEvents")
    if not incoming_keys or not isinstance(events, list):
        return message

    kept_events: list[dict[str, Any]] = []
    removed_trace_lines: set[str] = set()
    changed = False
    for event in events:
        if not isinstance(event, dict):
            continue
        key = _tool_event_file_edit_key(event)
        if key and key in incoming_keys:
            changed = True
            removed_trace_lines.update(tool_trace_lines_from_events([event]))
            continue
        kept_events.append(event)
    if not changed:
        return message

    raw_traces = message.get("traces")
    if isinstance(raw_traces, list):
        previous_traces = [trace for trace in raw_traces if isinstance(trace, str)]
    else:
        content = message.get("content")
        previous_traces = [content] if isinstance(content, str) and content else []
    next_traces = [trace for trace in previous_traces if trace not in removed_trace_lines]
    next_message = {
        **message,
        "traces": next_traces,
        "content": next_traces[-1] if next_traces else "",
    }
    if kept_events:
        next_message["toolEvents"] = kept_events
    else:
        next_message.pop("toolEvents", None)
    return next_message


def _merge_unique_tool_trace_lines(
    previous_traces: list[str],
    lines: list[str],
) -> tuple[list[str], bool]:
    seen_lines = set(previous_traces)
    traces = list(previous_traces)
    added = False
    for line in lines:
        if line in seen_lines:
            continue
        seen_lines.add(line)
        traces.append(line)
        added = True
    return traces, added


def _media_from_signed_urls(value: Any) -> list[dict[str, Any]]:
    media: list[dict[str, Any]] = []
    urls = value if isinstance(value, list) else []
    for m in urls:
        if isinstance(m, dict) and m.get("url"):
            name = str(m.get("name") or "")
            media.append(
                {
                    "kind": _media_kind_from_name(name),
                    "url": str(m["url"]),
                    "name": name,
                },
            )
    return media


def replay_transcript_to_ui_messages(
    lines: list[dict[str, Any]],
    *,
    augment_user_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_text: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Fold JSONL records into ``UIMessage``-shaped dicts for the WebUI.

    Mirrors the core fold in ``useNanobotStream.ts`` (delta, reasoning,
    message+kind, turn_end). ``augment_user_media`` maps persisted filesystem
    paths to ``{url, name?}`` / attachment dicts the client expects. Assistant
    media gets a separate hook so replay can re-sign outbound attachments after
    a gateway restart instead of reusing stale process-local signed URLs.
    """
    messages: list[dict[str, Any]] = []
    buffer_message_id: str | None = None
    buffer_parts: list[str] = []
    suppress_until_turn_end = False
    active_activity_segment_id: str | None = None
    active_file_edit_segment_id: str | None = None
    activity_segment_counter = 0
    _ts_base = int(time.time() * 1000)

    def _new_id(prefix: str, idx: int) -> str:
        return f"{prefix}-{idx}-{uuid.uuid4().hex[:8]}"

    def _new_activity_segment(*, activate: bool = True) -> str:
        nonlocal active_activity_segment_id, activity_segment_counter
        activity_segment_counter += 1
        segment_id = f"activity-{activity_segment_counter}"
        if activate:
            active_activity_segment_id = segment_id
        return segment_id

    def _ensure_activity_segment() -> str:
        return active_activity_segment_id or _new_activity_segment()

    def close_activity_for_answer() -> None:
        nonlocal active_activity_segment_id, active_file_edit_segment_id
        active_activity_segment_id = None
        active_file_edit_segment_id = None

    def close_file_edit_phase_before_activity() -> None:
        nonlocal active_activity_segment_id, active_file_edit_segment_id
        if active_file_edit_segment_id:
            active_activity_segment_id = None
            active_file_edit_segment_id = None

    def attach_reasoning_chunk(prev: list[dict[str, Any]], chunk: str, idx: int) -> None:
        for i in range(len(prev) - 1, -1, -1):
            candidate = prev[i]
            if candidate.get("role") == "user":
                break
            if candidate.get("kind") == "trace":
                break
            if candidate.get("role") != "assistant":
                continue
            content = str(candidate.get("content") or "")
            has_answer = len(content) > 0
            if (
                candidate.get("reasoningStreaming")
                or candidate.get("reasoning") is not None
                or has_answer
                or candidate.get("isStreaming")
            ):
                prev[i] = {
                    **candidate,
                    "reasoning": (str(candidate.get("reasoning") or "")) + chunk,
                    "reasoningStreaming": True,
                    "activitySegmentId": candidate.get("activitySegmentId") or _ensure_activity_segment(),
                }
                return
            if not has_answer and candidate.get("isStreaming"):
                prev[i] = {
                    **candidate,
                    "reasoning": chunk,
                    "reasoningStreaming": True,
                    "activitySegmentId": candidate.get("activitySegmentId") or _ensure_activity_segment(),
                }
                return
            break
        segment = _ensure_activity_segment()
        prev.append(
            {
                "id": _new_id("as", idx),
                "role": "assistant",
                "content": "",
                "isStreaming": True,
                "reasoning": chunk,
                "reasoningStreaming": True,
                "activitySegmentId": segment,
                "createdAt": _ts_base + idx,
            },
        )

    def find_active_placeholder(prev: list[dict[str, Any]]) -> str | None:
        last = prev[-1] if prev else None
        if not last:
            return None
        if last.get("role") != "assistant" or last.get("kind") == "trace":
            return None
        if str(last.get("content") or ""):
            return None
        if not last.get("isStreaming"):
            return None
        return str(last.get("id"))

    def demote_interrupted_assistant(segment: str) -> None:
        nonlocal buffer_message_id, buffer_parts
        for i in range(len(messages) - 1, -1, -1):
            candidate = messages[i]
            if candidate.get("role") == "user":
                break
            content = candidate.get("content")
            if (
                candidate.get("role") != "assistant"
                or candidate.get("kind") == "trace"
                or not candidate.get("isStreaming")
                or not isinstance(content, str)
                or not content.strip()
                or candidate.get("media")
            ):
                continue
            reasoning_parts = [
                part
                for part in (candidate.get("reasoning"), content)
                if isinstance(part, str) and part.strip()
            ]
            messages[i] = {
                **candidate,
                "content": "",
                "reasoning": "\n\n".join(reasoning_parts),
                "reasoningStreaming": False,
                "isStreaming": False,
                "activitySegmentId": candidate.get("activitySegmentId") or segment,
            }
            if buffer_message_id == candidate.get("id"):
                buffer_message_id = None
                buffer_parts = []
            return

    def close_reasoning(prev: list[dict[str, Any]]) -> None:
        for i in range(len(prev) - 1, -1, -1):
            if prev[i].get("reasoningStreaming"):
                prev[i] = {**prev[i], "reasoningStreaming": False}
                return

    def is_reasoning_only_placeholder(m: dict[str, Any]) -> bool:
        return (
            m.get("role") == "assistant"
            and m.get("kind") != "trace"
            and not str(m.get("content") or "").strip()
            and bool(m.get("reasoning"))
            and not m.get("reasoningStreaming")
            and not m.get("media")
        )

    def is_tool_trace_at(index: int) -> bool:
        m = messages[index] if 0 <= index < len(messages) else None
        return bool(m and m.get("kind") == "trace")

    def prune_reasoning_only() -> None:
        nonlocal messages
        kept: list[dict[str, Any]] = []
        for i, m in enumerate(messages):
            if is_reasoning_only_placeholder(m) and not is_tool_trace_at(i + 1):
                continue
            kept.append(m)
        messages = kept

    def stamp_latency(latency_ms: int) -> None:
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant" and messages[i].get("kind") != "trace":
                messages[i] = {
                    **messages[i],
                    "latencyMs": latency_ms,
                    "isStreaming": False,
                }
                return

    def absorb_complete(extra: dict[str, Any], idx: int) -> None:
        nonlocal active_activity_segment_id, active_file_edit_segment_id
        last = messages[-1] if messages else None
        if last and is_reasoning_only_placeholder(last):
            messages[-1] = {
                **last,
                **extra,
                "isStreaming": False,
                "reasoningStreaming": False,
            }
        else:
            messages.append(
                {
                    "id": _new_id("as", idx),
                    "role": "assistant",
                    "createdAt": _ts_base + idx,
                    **extra,
                },
            )
        active_activity_segment_id = None
        active_file_edit_segment_id = None

    def find_file_edit_trace_index(
        segment: str | None,
        edits: list[dict[str, Any]],
    ) -> int | None:
        incoming_keys = {_file_edit_key(edit) for edit in edits if isinstance(edit, dict)}
        for i in range(len(messages) - 1, -1, -1):
            candidate = messages[i]
            if candidate.get("role") == "user":
                break
            if candidate.get("kind") != "trace":
                continue
            if segment and candidate.get("activitySegmentId") == segment:
                return i
            existing_edits = candidate.get("fileEdits")
            if isinstance(existing_edits, list):
                for existing in existing_edits:
                    if isinstance(existing, dict) and _file_edit_key(existing) in incoming_keys:
                        return i
            existing_tool_events = candidate.get("toolEvents")
            if isinstance(existing_tool_events, list):
                for event in existing_tool_events:
                    if not isinstance(event, dict):
                        continue
                    key = _tool_event_file_edit_key(event)
                    if key and key in incoming_keys:
                        return i
        return None

    def upsert_file_edits(edits: list[dict[str, Any]], idx: int) -> None:
        nonlocal active_file_edit_segment_id
        if not edits:
            return
        segment = active_file_edit_segment_id
        if not segment:
            segment = _new_activity_segment(activate=False)
            active_file_edit_segment_id = segment
        demote_interrupted_assistant(segment)
        target_index = find_file_edit_trace_index(segment, edits)
        if target_index is not None:
            last = messages[target_index]
            segment = str(last.get("activitySegmentId") or segment or _new_activity_segment(activate=False))
            active_file_edit_segment_id = segment
            last = _strip_covered_file_edit_tool_hints(last, edits)
        else:
            if not segment:
                segment = _new_activity_segment(activate=False)
            active_file_edit_segment_id = segment
            messages.append(
                {
                    "id": _new_id("tr", idx),
                    "role": "tool",
                    "kind": "trace",
                    "content": "",
                    "traces": [],
                    "fileEdits": [],
                    "activitySegmentId": segment,
                    "createdAt": _ts_base + idx,
                },
            )
            target_index = len(messages) - 1
            last = messages[target_index]
        if not segment:
            segment = _new_activity_segment(activate=False)
            active_file_edit_segment_id = segment
        existing = list(last.get("fileEdits") or [])
        index_by_key = {
            _file_edit_key(edit): pos
            for pos, edit in enumerate(existing)
            if isinstance(edit, dict)
        }
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            key = _file_edit_key(edit)
            if key in index_by_key:
                pos = index_by_key[key]
                merged = {**existing[pos], **edit}
                if edit.get("path") and not edit.get("pending"):
                    merged.pop("pending", None)
                existing[pos] = merged
            else:
                index_by_key[key] = len(existing)
                existing.append(dict(edit))
        messages[target_index] = {
            **last,
            "fileEdits": existing,
            "activitySegmentId": last.get("activitySegmentId") or segment,
        }

    for idx, rec in enumerate(lines):
        ev = rec.get("event")
        if ev == "user":
            active_activity_segment_id = None
            active_file_edit_segment_id = None
            text = rec.get("text")
            text_s = text if isinstance(text, str) else ""
            media_paths = rec.get("media_paths")
            paths: list[str] = []
            if isinstance(media_paths, list):
                paths = [str(p) for p in media_paths if p]
            media_att: list[dict[str, Any]] | None = None
            if paths and augment_user_media is not None:
                media_att = augment_user_media(paths)
            row: dict[str, Any] = {
                "id": _new_id("u", idx),
                "role": "user",
                "content": text_s,
                "createdAt": _ts_base + idx,
            }
            if media_att:
                row["media"] = media_att
                if all(m.get("kind") == "image" for m in media_att):
                    row["images"] = [{"url": m.get("url"), "name": m.get("name")} for m in media_att]
            cli_apps = rec.get("cli_apps")
            if isinstance(cli_apps, list) and cli_apps:
                row["cliApps"] = [dict(app) for app in cli_apps if isinstance(app, dict)]
            mcp_presets = rec.get("mcp_presets")
            if isinstance(mcp_presets, list) and mcp_presets:
                row["mcpPresets"] = [
                    dict(preset) for preset in mcp_presets if isinstance(preset, dict)
                ]
            messages.append(row)
            continue

        if ev == "file_edit":
            raw_edits = rec.get("edits")
            if isinstance(raw_edits, list):
                upsert_file_edits([e for e in raw_edits if isinstance(e, dict)], idx)
            continue

        if ev == "delta":
            if suppress_until_turn_end:
                continue
            chunk = rec.get("text")
            if not isinstance(chunk, str):
                continue
            close_activity_for_answer()
            adopted = find_active_placeholder(messages) if buffer_message_id is None else None
            if buffer_message_id is None:
                if adopted:
                    buffer_message_id = adopted
                else:
                    buffer_message_id = _new_id("buf", idx)
                    messages.append(
                        {
                            "id": buffer_message_id,
                            "role": "assistant",
                            "content": "",
                            "isStreaming": True,
                            "createdAt": _ts_base + idx,
                        },
                    )
            buffer_parts.append(chunk)
            combined = "".join(buffer_parts)
            for i, m in enumerate(messages):
                if m.get("id") == buffer_message_id:
                    messages[i] = {**m, "content": combined, "isStreaming": True}
                    break
            continue

        if ev == "stream_end":
            if suppress_until_turn_end:
                buffer_message_id = None
                buffer_parts = []
                continue
            final_text = rec.get("text")
            if isinstance(final_text, str):
                if buffer_message_id is None:
                    buffer_message_id = _new_id("buf", idx)
                    messages.append(
                        {
                            "id": buffer_message_id,
                            "role": "assistant",
                            "content": final_text,
                            "isStreaming": True,
                            "createdAt": _ts_base + idx,
                        },
                    )
                else:
                    for i, m in enumerate(messages):
                        if m.get("id") == buffer_message_id:
                            messages[i] = {**m, "content": final_text, "isStreaming": True}
                            break
            buffer_message_id = None
            buffer_parts = []
            continue

        if ev == "reasoning_delta":
            if suppress_until_turn_end:
                continue
            chunk = rec.get("text")
            if not isinstance(chunk, str) or not chunk:
                continue
            close_file_edit_phase_before_activity()
            attach_reasoning_chunk(messages, chunk, idx)
            continue

        if ev == "reasoning_end":
            if suppress_until_turn_end:
                continue
            close_reasoning(messages)
            continue

        if ev == "message":
            if suppress_until_turn_end and rec.get("kind") in (
                "tool_hint",
                "progress",
                "reasoning",
            ):
                continue
            kind = rec.get("kind")
            if kind == "reasoning":
                line = rec.get("text")
                if not isinstance(line, str) or not line:
                    continue
                close_file_edit_phase_before_activity()
                attach_reasoning_chunk(messages, line, idx)
                close_reasoning(messages)
                continue
            if kind in ("tool_hint", "progress"):
                structured_events = _normalize_tool_events(rec.get("tool_events"))
                visible_structured_events = _filter_covered_file_edit_tool_events(messages, structured_events)
                structured = tool_trace_lines_from_events(visible_structured_events)
                text = rec.get("text")
                if structured:
                    trace_lines = structured
                elif structured_events:
                    trace_lines = []
                elif isinstance(text, str) and text:
                    trace_lines = [text]
                else:
                    trace_lines = []
                if not trace_lines:
                    continue
                segment = _ensure_activity_segment()
                demote_interrupted_assistant(segment)
                last = messages[-1] if messages else None
                if (
                    last
                    and last.get("kind") == "trace"
                    and not last.get("isStreaming")
                    and (last.get("activitySegmentId") in (None, segment))
                ):
                    prev_traces = list(last.get("traces") or [last.get("content")])
                    if structured:
                        merged_traces, added = _merge_unique_tool_trace_lines(prev_traces, structured)
                        if not added and not visible_structured_events:
                            continue
                    else:
                        merged_traces = prev_traces + trace_lines
                    merged = {
                        **last,
                        "traces": merged_traces,
                        "content": merged_traces[-1],
                        "toolEvents": _merge_tool_events(last.get("toolEvents"), visible_structured_events)
                        if visible_structured_events
                        else last.get("toolEvents"),
                        "activitySegmentId": last.get("activitySegmentId") or segment,
                    }
                    messages[-1] = merged
                else:
                    messages.append(
                        {
                            "id": _new_id("tr", idx),
                            "role": "tool",
                            "kind": "trace",
                            "content": trace_lines[-1],
                            "traces": trace_lines,
                            **({"toolEvents": visible_structured_events} if visible_structured_events else {}),
                            "activitySegmentId": segment,
                            "createdAt": _ts_base + idx,
                        },
                    )
                continue

            buffer_message_id = None
            buffer_parts = []
            text = rec.get("text")
            content_s = text if isinstance(text, str) else ""
            media: list[dict[str, Any]] = []
            raw_media = rec.get("media")
            raw_media_list = raw_media if isinstance(raw_media, list) else []
            media_paths = [path for path in raw_media_list if isinstance(path, str) and path]
            if media_paths and augment_assistant_media is not None:
                media = augment_assistant_media(media_paths)
            if not media and (not media_paths or augment_assistant_media is None):
                media = _media_from_signed_urls(rec.get("media_urls"))
            extra: dict[str, Any] = {"content": content_s}
            if media:
                extra["media"] = media
            lat = rec.get("latency_ms")
            if isinstance(lat, (int, float)) and lat >= 0:
                extra["latencyMs"] = int(lat)
            absorb_complete(extra, idx)
            if media:
                suppress_until_turn_end = True
            continue

        if ev == "turn_end":
            suppress_until_turn_end = False
            active_activity_segment_id = None
            active_file_edit_segment_id = None
            for i, m in enumerate(messages):
                if m.get("isStreaming"):
                    messages[i] = {**m, "isStreaming": False}
            prune_reasoning_only()
            lat = rec.get("latency_ms")
            if isinstance(lat, (int, float)) and lat >= 0:
                stamp_latency(int(lat))
            buffer_message_id = None
            buffer_parts = []
            continue

    for i, m in enumerate(messages):
        if (
            augment_assistant_text is not None
            and m.get("role") == "assistant"
            and m.get("kind") != "trace"
            and isinstance(m.get("content"), str)
        ):
            messages[i] = {**m, "content": augment_assistant_text(m["content"])}
        m.pop("isStreaming", None)
        m.pop("reasoningStreaming", None)
    return messages


def build_webui_thread_response(
    session_key: str,
    *,
    augment_user_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_text: Callable[[str], str] | None = None,
    session_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Return a payload compatible with ``WebuiThreadPersistedPayload``."""
    lines = read_transcript_lines(session_key)
    if not lines:
        return None
    lines = inject_missing_user_events_from_session(session_key, lines, session_messages)
    msgs = replay_transcript_to_ui_messages(
        lines,
        augment_user_media=augment_user_media,
        augment_assistant_media=augment_assistant_media,
        augment_assistant_text=augment_assistant_text,
    )
    return {
        "schemaVersion": WEBUI_TRANSCRIPT_SCHEMA_VERSION,
        "sessionKey": session_key,
        "messages": msgs,
    }
