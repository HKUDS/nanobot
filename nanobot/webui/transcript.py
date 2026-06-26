"""Append-only WebUI display transcript (JSONL), separate from agent session."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple
from urllib.parse import unquote, urlparse

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.cron.session_turns import CRON_HISTORY_META
from nanobot.session.manager import SessionManager
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY

WEBUI_TRANSCRIPT_SCHEMA_VERSION = 3
WEBUI_FORK_MARKER_EVENT = "fork_marker"
_MAX_TRANSCRIPT_FILE_BYTES = 8 * 1024 * 1024
_TARGET_ACTIVE_TRANSCRIPT_BYTES = _MAX_TRANSCRIPT_FILE_BYTES // 2
_TRANSCRIPT_SEGMENT_MANIFEST_VERSION = 2
_TRANSCRIPT_ACTIVE_CHUNK_ID = "active"
_TRANSCRIPT_SEGMENT_RE = re.compile(r"^\d{6}\.jsonl$")
_DEFAULT_TRANSCRIPT_PAGE_LIMIT = 160
_MAX_TRANSCRIPT_PAGE_LIMIT = 1000
_WEBUI_TURN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
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


def webui_transcript_segments_dir(session_key: str) -> Path:
    stem = SessionManager.safe_key(session_key)
    return get_webui_dir() / f"{stem}.segments"


def _webui_transcript_manifest_path(session_key: str) -> Path:
    return webui_transcript_segments_dir(session_key) / "manifest.json"


def _legacy_webui_thread_path(session_key: str) -> Path:
    stem = SessionManager.safe_key(session_key)
    return get_webui_dir() / f"{stem}.json"


class _TranscriptTurnRef(NamedTuple):
    ordinal: int
    records: list[dict[str, Any]]


class _TranscriptChunkRef(NamedTuple):
    chunk_id: str
    start_ordinal: int
    turn_count: int
    user_count: int


def _record_json_line(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def _read_transcript_file(path: Path) -> list[dict[str, Any]]:
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


def _records_bytes(records: list[dict[str, Any]]) -> int:
    total = 0
    for record in records:
        total += len(_record_json_line(record).encode("utf-8")) + 1
    return total


def _flatten_turns(turns: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [record for turn in turns for record in turn]


def _write_records_to_path(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            for row in rows:
                raw = _record_json_line(row)
                if len(raw.encode("utf-8")) > _MAX_TRANSCRIPT_FILE_BYTES:
                    raise ValueError("webui transcript line too large")
                f.write(raw + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _segment_file_path(session_key: str, segment_id: str) -> Path:
    return webui_transcript_segments_dir(session_key) / f"{segment_id}.jsonl"


def _segment_ids_on_disk(session_key: str) -> list[str]:
    directory = webui_transcript_segments_dir(session_key)
    if not directory.is_dir():
        return []
    return sorted(
        path.stem
        for path in directory.iterdir()
        if path.is_file() and _TRANSCRIPT_SEGMENT_RE.fullmatch(path.name)
    )


def _segment_manifest_entry(session_key: str, segment_id: str) -> dict[str, Any]:
    path = _segment_file_path(session_key, segment_id)
    lines = _read_transcript_file(path)
    return {
        "id": segment_id,
        "bytes": path.stat().st_size if path.exists() else 0,
        "turn_count": len(_split_transcript_turns(lines)),
        "user_count": sum(1 for line in lines if _is_user_transcript_row(line)),
    }


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _normalize_manifest_entry(session_key: str, entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    segment_id = entry.get("id")
    if not isinstance(segment_id, str) or not _TRANSCRIPT_SEGMENT_RE.fullmatch(f"{segment_id}.jsonl"):
        return None
    segment_path = _segment_file_path(session_key, segment_id)
    values = {
        key: _non_negative_int(entry.get(key))
        for key in ("bytes", "turn_count", "user_count")
    }
    if not segment_path.is_file() or values["bytes"] != segment_path.stat().st_size:
        return None
    if values["turn_count"] is None or values["user_count"] is None:
        return None
    return {
        "id": segment_id,
        "bytes": values["bytes"],
        "turn_count": values["turn_count"],
        "user_count": values["user_count"],
    }


def _write_segment_manifest(session_key: str, segment_ids: list[str]) -> None:
    directory = webui_transcript_segments_dir(session_key)
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "version": _TRANSCRIPT_SEGMENT_MANIFEST_VERSION,
        "segments": [_segment_manifest_entry(session_key, segment_id) for segment_id in segment_ids],
    }
    path = _webui_transcript_manifest_path(session_key)
    tmp_path = path.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _rebuild_segment_manifest(session_key: str) -> list[str]:
    segment_ids = _segment_ids_on_disk(session_key)
    if segment_ids:
        _write_segment_manifest(session_key, segment_ids)
    else:
        _webui_transcript_manifest_path(session_key).unlink(missing_ok=True)
    return segment_ids


def _rebuilt_segment_manifest_entries(session_key: str) -> list[dict[str, Any]]:
    return [_segment_manifest_entry(session_key, segment_id) for segment_id in _rebuild_segment_manifest(session_key)]


def _read_segment_manifest_entries(session_key: str) -> list[dict[str, Any]]:
    directory = webui_transcript_segments_dir(session_key)
    if not directory.is_dir():
        return []
    path = _webui_transcript_manifest_path(session_key)
    if not path.is_file():
        return _rebuilt_segment_manifest_entries(session_key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_segments = data.get("segments") if isinstance(data, dict) else None
        if data.get("version") != _TRANSCRIPT_SEGMENT_MANIFEST_VERSION or not isinstance(raw_segments, list):
            return _rebuilt_segment_manifest_entries(session_key)
        entries: list[dict[str, Any]] = []
        for entry in raw_segments:
            normalized = _normalize_manifest_entry(session_key, entry)
            if normalized is None:
                return _rebuilt_segment_manifest_entries(session_key)
            entries.append(normalized)
        if [entry["id"] for entry in entries] != _segment_ids_on_disk(session_key):
            return _rebuilt_segment_manifest_entries(session_key)
        return entries
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        return _rebuilt_segment_manifest_entries(session_key)


def _read_segment_ids(session_key: str) -> list[str]:
    return [entry["id"] for entry in _read_segment_manifest_entries(session_key)]


def _append_segment_turns(session_key: str, turns: list[list[dict[str, Any]]]) -> None:
    if not turns:
        return
    segment_ids = _read_segment_ids(session_key)
    next_id = int(segment_ids[-1]) + 1 if segment_ids else 1
    batch: list[list[dict[str, Any]]] = []
    batch_bytes = 0
    for turn in turns:
        turn_bytes = _records_bytes(turn)
        if batch and batch_bytes + turn_bytes > _MAX_TRANSCRIPT_FILE_BYTES:
            segment_id = f"{next_id:06d}"
            _write_records_to_path(_segment_file_path(session_key, segment_id), _flatten_turns(batch))
            segment_ids.append(segment_id)
            next_id += 1
            batch = []
            batch_bytes = 0
        batch.append(turn)
        batch_bytes += turn_bytes
    if batch:
        segment_id = f"{next_id:06d}"
        _write_records_to_path(_segment_file_path(session_key, segment_id), _flatten_turns(batch))
        segment_ids.append(segment_id)
    _write_segment_manifest(session_key, segment_ids)


def _rotate_active_transcript_if_needed(session_key: str) -> None:
    path = webui_transcript_path(session_key)
    if not path.is_file():
        return
    try:
        if path.stat().st_size <= _MAX_TRANSCRIPT_FILE_BYTES:
            return
    except OSError:
        return

    lines = _read_transcript_file(path)
    if not lines:
        return
    turns = _split_transcript_turns(lines)
    if len(turns) <= 1:
        return

    keep_start = len(turns) - 1
    keep_bytes = 0
    for idx in range(len(turns) - 1, -1, -1):
        turn_bytes = _records_bytes(turns[idx])
        if idx == len(turns) - 1 or keep_bytes + turn_bytes <= _TARGET_ACTIVE_TRANSCRIPT_BYTES:
            keep_start = idx
            keep_bytes += turn_bytes
            continue
        break

    moved = turns[:keep_start]
    kept = turns[keep_start:]
    if not moved:
        return
    _append_segment_turns(session_key, moved)
    _write_records_to_path(path, _flatten_turns(kept))


def _chunk_ids(session_key: str) -> list[str]:
    _rotate_active_transcript_if_needed(session_key)
    ids = _read_segment_ids(session_key)
    if webui_transcript_path(session_key).is_file():
        ids.append(_TRANSCRIPT_ACTIVE_CHUNK_ID)
    return ids


def _read_chunk_turns(session_key: str, chunk_id: str) -> list[list[dict[str, Any]]]:
    if chunk_id == _TRANSCRIPT_ACTIVE_CHUNK_ID:
        path = webui_transcript_path(session_key)
    else:
        path = _segment_file_path(session_key, chunk_id)
    if not path.is_file():
        return []
    return _split_transcript_turns(_read_transcript_file(path))


def _encode_page_cursor(before_turn_ordinal: int) -> str:
    raw = json.dumps(
        {"before_turn": before_turn_ordinal},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_page_cursor(value: str | None) -> int | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    before_turn = data.get("before_turn")
    if (
        isinstance(before_turn, bool)
        or not isinstance(before_turn, int)
        or before_turn < 0
    ):
        return None
    return before_turn


def _coerce_page_limit(limit: int | None) -> int:
    if limit is None:
        return _DEFAULT_TRANSCRIPT_PAGE_LIMIT
    return max(1, min(_MAX_TRANSCRIPT_PAGE_LIMIT, int(limit)))


def _chunk_turn_refs(session_key: str) -> list[_TranscriptChunkRef]:
    _rotate_active_transcript_if_needed(session_key)
    refs: list[_TranscriptChunkRef] = []
    ordinal = 0
    for entry in _read_segment_manifest_entries(session_key):
        chunk_id = str(entry["id"])
        turn_count = int(entry["turn_count"])
        if turn_count <= 0:
            continue
        refs.append(_TranscriptChunkRef(chunk_id, ordinal, turn_count, int(entry["user_count"])))
        ordinal += turn_count
    if webui_transcript_path(session_key).is_file():
        active_turns = _read_chunk_turns(session_key, _TRANSCRIPT_ACTIVE_CHUNK_ID)
        active_turn_count = len(active_turns)
        if active_turn_count > 0:
            refs.append(
                _TranscriptChunkRef(
                    _TRANSCRIPT_ACTIVE_CHUNK_ID,
                    ordinal,
                    active_turn_count,
                    sum(1 for turn in active_turns for row in turn if _is_user_transcript_row(row)),
                ),
            )
    return refs


def _count_user_messages_before_ordinal(
    session_key: str,
    chunks: list[_TranscriptChunkRef],
    before_ordinal: int,
) -> int:
    total = 0
    for chunk in chunks:
        if before_ordinal <= chunk.start_ordinal:
            break
        local_end = min(chunk.turn_count, before_ordinal - chunk.start_ordinal)
        if local_end <= 0:
            continue
        if local_end >= chunk.turn_count:
            total += chunk.user_count
            continue
        turns = _read_chunk_turns(session_key, chunk.chunk_id)
        total += sum(
            1
            for turn in turns[:local_end]
            for row in turn
            if _is_user_transcript_row(row)
        )
    return total


def _select_transcript_page(
    session_key: str,
    *,
    limit: int | None,
    before: str | None,
    _manifest_rebuilt: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page_limit = _coerce_page_limit(limit)
    chunks = _chunk_turn_refs(session_key)
    total_turns = sum(chunk.turn_count for chunk in chunks)
    before_ordinal = _decode_page_cursor(before)
    upper_ordinal = total_turns if before_ordinal is None else min(before_ordinal, total_turns)
    selected: list[_TranscriptTurnRef] = []
    selected_message_count = 0

    for chunk in reversed(chunks):
        if chunk.start_ordinal >= upper_ordinal:
            continue
        local_upper = min(chunk.turn_count, upper_ordinal - chunk.start_ordinal)
        if local_upper <= 0:
            continue
        turns = _read_chunk_turns(session_key, chunk.chunk_id)
        if (
            chunk.chunk_id != _TRANSCRIPT_ACTIVE_CHUNK_ID
            and len(turns) != chunk.turn_count
            and not _manifest_rebuilt
        ):
            _rebuild_segment_manifest(session_key)
            return _select_transcript_page(
                session_key,
                limit=limit,
                before=before,
                _manifest_rebuilt=True,
            )
        local_upper = min(local_upper, len(turns))
        for turn_index in range(local_upper - 1, -1, -1):
            ordinal = chunk.start_ordinal + turn_index
            turn = turns[turn_index]
            selected.append(_TranscriptTurnRef(ordinal, turn))
            selected_message_count += len(replay_transcript_to_ui_messages(turn))
            if selected_message_count >= page_limit:
                break
        if selected_message_count >= page_limit:
            break

    selected_chronological = list(reversed(selected))
    lines = [record for ref in selected_chronological for record in ref.records]
    if not selected_chronological:
        return [], {
            "before_cursor": None,
            "has_more_before": False,
            "loaded_message_count": 0,
            "user_message_offset": 0,
        }

    first_ref = selected_chronological[0]
    has_more = first_ref.ordinal > 0
    page = {
        "before_cursor": _encode_page_cursor(first_ref.ordinal) if has_more else None,
        "has_more_before": has_more,
        "loaded_message_count": 0,
        "user_message_offset": _count_user_messages_before_ordinal(
            session_key,
            chunks,
            first_ref.ordinal,
        ),
    }
    return lines, page


def read_transcript_lines(session_key: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for chunk_id in _chunk_ids(session_key):
        if chunk_id == _TRANSCRIPT_ACTIVE_CHUNK_ID:
            lines.extend(_read_transcript_file(webui_transcript_path(session_key)))
        else:
            lines.extend(_read_transcript_file(_segment_file_path(session_key, chunk_id)))
    return lines


def _write_transcript_lines(session_key: str, rows: list[dict[str, Any]]) -> None:
    delete_webui_transcript(session_key)
    path = webui_transcript_path(session_key)
    _write_records_to_path(path, rows)
    _rotate_active_transcript_if_needed(session_key)


def _append_to_active_transcript(session_key: str, obj: dict[str, Any]) -> None:
    raw = _record_json_line(obj)
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


def append_transcript_object(session_key: str, obj: dict[str, Any]) -> None:
    _append_to_active_transcript(session_key, obj)
    if obj.get("event") == "turn_end":
        _rotate_active_transcript_if_needed(session_key)


def normalize_webui_turn_id(value: Any) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if _WEBUI_TURN_ID_RE.fullmatch(candidate):
            return candidate
    return str(uuid.uuid4())


def webui_message_source(metadata: dict[str, Any] | None) -> dict[str, str] | None:
    raw = (metadata or {}).get(WEBUI_MESSAGE_SOURCE_METADATA_KEY)
    if not isinstance(raw, dict) or raw.get("kind") != "cron":
        return None
    source: dict[str, str] = {"kind": "cron"}
    label = raw.get("label")
    if isinstance(label, str) and label.strip():
        source["label"] = label.strip()
    return source


class WebUITranscriptRecorder:
    """Prepare and persist WebUI wire events without leaking UI rules into channels."""

    def __init__(self, log: Any = logger) -> None:
        self._log = log
        self._turn_sequences: dict[tuple[str, str], int] = {}

    def client_turn_metadata(self, value: Any) -> dict[str, str]:
        return {WEBUI_TURN_METADATA_KEY: normalize_webui_turn_id(value)}

    def prepare_event(
        self,
        chat_id: str,
        event: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
        phase: str | None = None,
        include_source: bool = False,
    ) -> None:
        if include_source and (source := webui_message_source(metadata)):
            event["source"] = source
        self._annotate_turn(chat_id, event, metadata, phase)

    def prepare_and_append(
        self,
        chat_id: str,
        event: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
        phase: str | None = None,
        include_source: bool = False,
        transcript_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.prepare_event(
            chat_id,
            event,
            metadata=metadata,
            phase=phase,
            include_source=include_source,
        )
        record = dict(event)
        if transcript_overrides:
            record.update(transcript_overrides)
        self.append(chat_id, record)

    def append_user_message(
        self,
        chat_id: str,
        text: str,
        *,
        metadata: dict[str, Any],
        media_paths: list[str] | None = None,
        cli_apps: list[dict[str, Any]] | None = None,
        mcp_presets: list[dict[str, Any]] | None = None,
    ) -> None:
        if text.strip() == "/stop" and not media_paths:
            return
        payload = build_user_transcript_event(
            chat_id,
            text,
            media_paths=media_paths,
            cli_apps=cli_apps,
            mcp_presets=mcp_presets,
        )
        if payload is None:
            return
        self.prepare_and_append(chat_id, payload, metadata=metadata, phase="user")

    def append(self, chat_id: str, event: dict[str, Any]) -> None:
        try:
            dup = json.loads(json.dumps(event, ensure_ascii=False))
            append_transcript_object(f"websocket:{chat_id}", dup)
        except (OSError, ValueError, TypeError) as e:
            self._log.warning("webui transcript append failed: {}", e)

    def _next_turn_seq(self, chat_id: str, turn_id: str) -> int:
        key = (chat_id, turn_id)
        seq = self._turn_sequences.get(key, 0) + 1
        self._turn_sequences[key] = seq
        return seq

    def _annotate_turn(
        self,
        chat_id: str,
        event: dict[str, Any],
        metadata: dict[str, Any] | None,
        phase: str | None,
    ) -> None:
        if phase is None:
            return
        turn_id = (metadata or {}).get(WEBUI_TURN_METADATA_KEY)
        if not isinstance(turn_id, str) or not turn_id:
            return
        event["turn_id"] = turn_id
        event["turn_phase"] = phase
        event["turn_seq"] = self._next_turn_seq(chat_id, turn_id)
        if phase == "complete":
            self._turn_sequences.pop((chat_id, turn_id), None)


def _chat_id_from_session_key(session_key: str) -> str | None:
    if not session_key.startswith("websocket:"):
        return None
    chat_id = session_key.split(":", 1)[1].strip()
    return chat_id or None


def _is_user_transcript_row(row: dict[str, Any]) -> bool:
    return row.get("event") == "user" or row.get("role") == "user"


def fork_transcript_before_user_index(
    source_key: str,
    target_key: str,
    before_user_index: int,
) -> bool:
    """Copy transcript rows before a zero-based global user-message index.

    ``before_user_index == user_count`` copies the full transcript prefix. WebUI
    uses that when forking from an assistant reply at the end of a chat.
    """
    if before_user_index < 0:
        return False
    lines = read_transcript_lines(source_key)
    if not lines:
        return False

    target_chat_id = _chat_id_from_session_key(target_key)
    copied: list[dict[str, Any]] = []
    user_index = 0
    found_target = False
    for row in lines:
        if row.get("event") == WEBUI_FORK_MARKER_EVENT:
            continue
        if _is_user_transcript_row(row):
            if user_index == before_user_index:
                found_target = True
                break
            user_index += 1
        dup = json.loads(json.dumps(row, ensure_ascii=False))
        if target_chat_id is not None:
            dup["chat_id"] = target_chat_id
        copied.append(dup)
    if user_index == before_user_index:
        found_target = True

    if not found_target:
        return False

    _write_transcript_lines(target_key, copied)
    return True


def append_fork_marker(session_key: str) -> None:
    """Mark the UI-only boundary where a WebUI fork starts accepting new turns."""
    append_transcript_object(
        session_key,
        {
            "event": WEBUI_FORK_MARKER_EVENT,
            "chat_id": _chat_id_from_session_key(session_key),
        },
    )


def write_session_messages_as_transcript(
    target_key: str,
    messages: list[dict[str, Any]],
) -> None:
    """Write a minimal WebUI transcript from already-truncated session messages."""
    target_chat_id = _chat_id_from_session_key(target_key)
    rows: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        text = content if isinstance(content, str) else ""
        if role == "user":
            row: dict[str, Any] = {"event": "user", "chat_id": target_chat_id, "text": text}
            media = msg.get("media")
            if isinstance(media, list) and media:
                row["media_paths"] = [str(p) for p in media if isinstance(p, str) and p]
            for key in ("cli_apps", "mcp_presets"):
                value = msg.get(key)
                if isinstance(value, list) and value:
                    row[key] = json.loads(json.dumps(value, ensure_ascii=False))
        elif role == "assistant" and text.strip():
            row = {"event": "message", "chat_id": target_chat_id, "text": text}
            media = msg.get("media")
            if isinstance(media, list) and media:
                row["media"] = [str(p) for p in media if isinstance(p, str) and p]
        else:
            continue
        rows.append(row)
    _write_transcript_lines(target_key, rows)


def delete_webui_transcript(session_key: str) -> bool:
    removed = False
    for path in (webui_transcript_path(session_key), _legacy_webui_thread_path(session_key)):
        if not path.is_file():
            continue
        try:
            path.unlink()
            removed = True
        except OSError as e:
            logger.warning("Failed to delete webui transcript {}: {}", path, e)
    segments_dir = webui_transcript_segments_dir(session_key)
    if segments_dir.is_dir():
        try:
            shutil.rmtree(segments_dir)
            removed = True
        except OSError as e:
            logger.warning("Failed to delete webui transcript segments {}: {}", segments_dir, e)
    return removed


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
    if message.get(CRON_HISTORY_META) is True:
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
    path = str(edit.get("path") or "")
    if call_id and path:
        return f"{call_id}|{tool}|{path}"
    if call_id:
        return f"{call_id}|{tool}"
    return f"{tool}|{path}"


def _file_edit_tool_event_key(edit: dict[str, Any]) -> str:
    call_id = str(edit.get("call_id") or "")
    tool = str(edit.get("tool") or "")
    if call_id:
        return f"{call_id}|{tool}"
    return _file_edit_key(edit)


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
    return any(
        isinstance(edit, dict) and _file_edit_tool_event_key(edit) == key
        for edit in edits
    )


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
        _file_edit_tool_event_key(edit)
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
    closed_turn_ids: set[str] = set()
    replay_turn_aliases: dict[str, str] = {}

    def _new_id(prefix: str, idx: int) -> str:
        return f"{prefix}-{idx}-{uuid.uuid4().hex[:8]}"

    def _new_activity_segment(*, activate: bool = True) -> str:
        nonlocal active_activity_segment_id, activity_segment_counter
        activity_segment_counter += 1
        segment_id = f"activity-{activity_segment_counter}"
        if activate:
            active_activity_segment_id = segment_id
        return segment_id

    def _turn_fields(rec: dict[str, Any], fallback_phase: str | None = None) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        turn_id = rec.get("turn_id")
        if isinstance(turn_id, str) and turn_id:
            if turn_id in closed_turn_ids:
                fields["turnId"] = replay_turn_aliases.setdefault(
                    turn_id,
                    f"{turn_id}:replay:{idx}",
                )
            else:
                fields["turnId"] = turn_id
        phase = rec.get("turn_phase")
        if isinstance(phase, str) and phase:
            fields["turnPhase"] = phase
        elif fallback_phase:
            fields["turnPhase"] = fallback_phase
        seq = rec.get("turn_seq")
        if isinstance(seq, (int, float)):
            fields["turnSeq"] = int(seq)
        return fields

    def _source_fields(rec: dict[str, Any]) -> dict[str, Any]:
        source = rec.get("source")
        if not isinstance(source, dict) or source.get("kind") != "cron":
            return {}
        out: dict[str, Any] = {"source": {"kind": "cron"}}
        label = source.get("label")
        if isinstance(label, str) and label.strip():
            out["source"]["label"] = label.strip()
        return out

    def _same_turn(message: dict[str, Any], turn_fields: dict[str, Any]) -> bool:
        turn_id = turn_fields.get("turnId")
        message_turn_id = message.get("turnId")
        return not turn_id or not message_turn_id or turn_id == message_turn_id

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

    def attach_reasoning_chunk(
        prev: list[dict[str, Any]],
        chunk: str,
        idx: int,
        turn_fields: dict[str, Any] | None = None,
    ) -> None:
        turn_fields = turn_fields or {}
        for i in range(len(prev) - 1, -1, -1):
            candidate = prev[i]
            if candidate.get("role") == "user":
                break
            if candidate.get("kind") == "trace":
                break
            if candidate.get("role") != "assistant":
                continue
            if not _same_turn(candidate, turn_fields):
                break
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
                    **turn_fields,
                }
                return
            if not has_answer and candidate.get("isStreaming"):
                prev[i] = {
                    **candidate,
                    "reasoning": chunk,
                    "reasoningStreaming": True,
                    "activitySegmentId": candidate.get("activitySegmentId") or _ensure_activity_segment(),
                    **turn_fields,
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
                **turn_fields,
                "createdAt": _ts_base + idx,
            },
        )

    def find_active_placeholder(
        prev: list[dict[str, Any]],
        turn_fields: dict[str, Any] | None = None,
    ) -> str | None:
        turn_fields = turn_fields or {}
        last = prev[-1] if prev else None
        if not last:
            return None
        if last.get("role") != "assistant" or last.get("kind") == "trace":
            return None
        if str(last.get("content") or ""):
            return None
        if not last.get("isStreaming"):
            return None
        if not _same_turn(last, turn_fields):
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
        if last and is_reasoning_only_placeholder(last) and _same_turn(last, extra):
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
        incoming_tool_event_keys = {
            _file_edit_tool_event_key(edit)
            for edit in edits
            if isinstance(edit, dict)
        }
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
                    if not isinstance(existing, dict):
                        continue
                    if (
                        _file_edit_key(existing) in incoming_keys
                        or (
                            not existing.get("path")
                            and existing.get("pending")
                            and _file_edit_tool_event_key(existing) in incoming_tool_event_keys
                        )
                    ):
                        return i
            existing_tool_events = candidate.get("toolEvents")
            if isinstance(existing_tool_events, list):
                for event in existing_tool_events:
                    if not isinstance(event, dict):
                        continue
                    key = _tool_event_file_edit_key(event)
                    if key and key in incoming_tool_event_keys:
                        return i
        return None

    def upsert_file_edits(
        edits: list[dict[str, Any]],
        idx: int,
        turn_fields: dict[str, Any] | None = None,
    ) -> None:
        nonlocal active_file_edit_segment_id
        turn_fields = turn_fields or {}
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
                    **turn_fields,
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
            pos = index_by_key.get(key)
            if pos is None and edit.get("path"):
                event_key = _file_edit_tool_event_key(edit)
                for existing_pos, existing_edit in enumerate(existing):
                    if (
                        isinstance(existing_edit, dict)
                        and not existing_edit.get("path")
                        and existing_edit.get("pending")
                        and _file_edit_tool_event_key(existing_edit) == event_key
                    ):
                        pos = existing_pos
                        break
            if pos is not None:
                merged = {**existing[pos], **edit}
                if edit.get("path") and not edit.get("pending"):
                    merged.pop("pending", None)
                existing[pos] = merged
                index_by_key[key] = pos
            else:
                index_by_key[key] = len(existing)
                existing.append(dict(edit))
        messages[target_index] = {
            **last,
            "fileEdits": existing,
            "activitySegmentId": last.get("activitySegmentId") or segment,
            **turn_fields,
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
                **_turn_fields(rec, "user"),
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
                upsert_file_edits(
                    [e for e in raw_edits if isinstance(e, dict)],
                    idx,
                    _turn_fields(rec, "activity"),
                )
            continue

        if ev == "delta":
            if suppress_until_turn_end:
                continue
            chunk = rec.get("text")
            if not isinstance(chunk, str):
                continue
            close_activity_for_answer()
            turn_fields = _turn_fields(rec, "answer")
            adopted = find_active_placeholder(messages, turn_fields) if buffer_message_id is None else None
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
                            **_turn_fields(rec, "answer"),
                            "createdAt": _ts_base + idx,
                        },
                    )
            buffer_parts.append(chunk)
            combined = "".join(buffer_parts)
            for i, m in enumerate(messages):
                if m.get("id") == buffer_message_id:
                    messages[i] = {
                        **m,
                        "content": combined,
                        "isStreaming": True,
                        **_turn_fields(rec, "answer"),
                    }
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
                            **_turn_fields(rec, "answer"),
                            "createdAt": _ts_base + idx,
                        },
                    )
                else:
                    for i, m in enumerate(messages):
                        if m.get("id") == buffer_message_id:
                            messages[i] = {
                                **m,
                                "content": final_text,
                                "isStreaming": True,
                                **_turn_fields(rec, "answer"),
                            }
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
            attach_reasoning_chunk(messages, chunk, idx, _turn_fields(rec, "reasoning"))
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
                attach_reasoning_chunk(messages, line, idx, _turn_fields(rec, "reasoning"))
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
                        **_turn_fields(rec, "activity"),
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
                            **_turn_fields(rec, "activity"),
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
            extra.update(_turn_fields(rec, "answer"))
            extra.update(_source_fields(rec))
            absorb_complete(extra, idx)
            if media:
                suppress_until_turn_end = True
            continue

        if ev == "turn_end":
            suppress_until_turn_end = False
            active_activity_segment_id = None
            active_file_edit_segment_id = None
            turn_id = rec.get("turn_id")
            if isinstance(turn_id, str) and turn_id:
                if turn_id in replay_turn_aliases:
                    replay_turn_aliases.pop(turn_id, None)
                else:
                    closed_turn_ids.add(turn_id)
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


def fork_boundary_message_count(lines: list[dict[str, Any]]) -> int | None:
    """Return the replayed UI message count before the first fork marker, if any."""
    for idx, rec in enumerate(lines):
        if rec.get("event") != WEBUI_FORK_MARKER_EVENT:
            continue
        return len(replay_transcript_to_ui_messages(lines[:idx]))
    return None


def has_pending_tool_calls(lines: list[dict[str, Any]]) -> bool:
    """Return True when the selected transcript tail looks like an unfinished turn."""
    for rec in reversed(lines):
        ev = rec.get("event")
        if ev == "turn_end":
            return False
        if ev == "user":
            return False
        if ev == "message":
            return rec.get("kind") in {"tool_hint", "progress", "reasoning"}
        if ev in {
            "delta",
            "stream_end",
            "reasoning_delta",
            "reasoning_end",
            "file_edit",
        }:
            return True
        if ev in {WEBUI_FORK_MARKER_EVENT}:
            continue
    return False


def build_webui_thread_response(
    session_key: str,
    *,
    augment_user_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_text: Callable[[str], str] | None = None,
    session_messages: list[dict[str, Any]] | None = None,
    limit: int | None = None,
    direction: str | None = None,
    before: str | None = None,
) -> dict[str, Any] | None:
    """Return a payload compatible with ``WebuiThreadPersistedPayload``."""
    paginated = limit is not None or direction is not None or before is not None
    page: dict[str, Any] | None = None
    if paginated:
        lines, page = _select_transcript_page(session_key, limit=limit, before=before)
    else:
        lines = read_transcript_lines(session_key)
    if not lines:
        return None
    lines = inject_missing_user_events_from_session(session_key, lines, session_messages)
    fork_boundary = fork_boundary_message_count(lines)
    msgs = replay_transcript_to_ui_messages(
        lines,
        augment_user_media=augment_user_media,
        augment_assistant_media=augment_assistant_media,
        augment_assistant_text=augment_assistant_text,
    )
    payload = {
        "schemaVersion": WEBUI_TRANSCRIPT_SCHEMA_VERSION,
        "sessionKey": session_key,
        "messages": msgs,
        "has_pending_tool_calls": has_pending_tool_calls(lines),
    }
    if page is not None:
        page["loaded_message_count"] = len(msgs)
        payload["page"] = page
    if fork_boundary is not None:
        payload["fork_boundary_message_count"] = fork_boundary
    return payload
