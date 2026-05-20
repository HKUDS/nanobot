"""Append-only WebUI display transcript (JSONL), separate from agent session."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.session.manager import SessionManager

WEBUI_TRANSCRIPT_SCHEMA_VERSION = 3
_MAX_TRANSCRIPT_FILE_BYTES = 8 * 1024 * 1024


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


def replay_transcript_to_ui_messages(
    lines: list[dict[str, Any]],
    *,
    augment_user_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Fold JSONL records into ``UIMessage``-shaped dicts for the WebUI.

    Mirrors the core fold in ``useNanobotStream.ts`` (delta, reasoning,
    message+kind, turn_end). ``augment_user_media`` maps persisted filesystem
    paths to ``{url, name?}`` / attachment dicts the client expects.
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

    def _file_edit_key(edit: dict[str, Any]) -> str:
        call_id = str(edit.get("call_id") or "")
        tool = str(edit.get("tool") or "")
        if call_id:
            return f"{call_id}|{tool}"
        return f"{tool}|{edit.get('path') or ''}"

    def find_file_edit_trace_index(
        segment: str | None,
        edits: list[dict[str, Any]],
    ) -> int | None:
        incoming_keys = {_file_edit_key(edit) for edit in edits if isinstance(edit, dict)}
        for i in range(len(messages) - 1, -1, -1):
            candidate = messages[i]
            if candidate.get("role") == "user":
                break
            if candidate.get("kind") != "trace" or not candidate.get("fileEdits"):
                continue
            if segment and candidate.get("activitySegmentId") == segment:
                return i
            existing_edits = candidate.get("fileEdits")
            if not isinstance(existing_edits, list):
                continue
            for existing in existing_edits:
                if isinstance(existing, dict) and _file_edit_key(existing) in incoming_keys:
                    return i
        return None

    def upsert_file_edits(edits: list[dict[str, Any]], idx: int) -> None:
        nonlocal active_file_edit_segment_id
        if not edits:
            return
        segment = active_file_edit_segment_id
        target_index = find_file_edit_trace_index(segment, edits)
        if target_index is not None:
            last = messages[target_index]
            segment = str(last.get("activitySegmentId") or segment or _new_activity_segment(activate=False))
            active_file_edit_segment_id = segment
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
                structured = tool_trace_lines_from_events(rec.get("tool_events"))
                text = rec.get("text")
                trace_lines = structured if structured else ([text] if isinstance(text, str) and text else [])
                if not trace_lines:
                    continue
                segment = _ensure_activity_segment()
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
                        if not added:
                            continue
                    else:
                        merged_traces = prev_traces + trace_lines
                    merged = {
                        **last,
                        "traces": merged_traces,
                        "content": merged_traces[-1],
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
                            "activitySegmentId": segment,
                            "createdAt": _ts_base + idx,
                        },
                    )
                continue

            buffer_message_id = None
            buffer_parts = []
            text = rec.get("text")
            content_s = text if isinstance(text, str) else ""
            media_urls = rec.get("media_urls")
            media: list[dict[str, Any]] = []
            if isinstance(media_urls, list):
                for m in media_urls:
                    if isinstance(m, dict) and m.get("url"):
                        media.append(
                            {
                                "kind": "image",
                                "url": str(m["url"]),
                                "name": str(m.get("name") or ""),
                            },
                        )
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

    for m in messages:
        m.pop("isStreaming", None)
        m.pop("reasoningStreaming", None)
    return messages


def build_webui_thread_response(
    session_key: str,
    *,
    augment_user_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Return a payload compatible with ``WebuiThreadPersistedPayload``."""
    lines = read_transcript_lines(session_key)
    if not lines:
        return None
    msgs = replay_transcript_to_ui_messages(lines, augment_user_media=augment_user_media)
    return {
        "schemaVersion": WEBUI_TRANSCRIPT_SCHEMA_VERSION,
        "sessionKey": session_key,
        "messages": msgs,
    }
