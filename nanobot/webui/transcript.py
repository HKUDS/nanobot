"""Append-only WebUI display transcript (JSONL), separate from agent session."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, Sequence, cast
from urllib.parse import unquote, urlparse

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.runtime_context import public_history_message
from nanobot.session.automation_turns import is_automation_kind
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import SessionManager
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY
from nanobot.webui.session_identity import webui_chat_id, webui_session_key

WEBUI_TRANSCRIPT_SCHEMA_VERSION = 3
WEBUI_FORK_MARKER_EVENT = "fork_marker"
WEBUI_TRANSCRIPT_INCOMPLETE_KEY = "transcript_incomplete"
_MAX_TRANSCRIPT_FILE_BYTES = 8 * 1024 * 1024
_ACTIVE_TRANSCRIPT_ROTATE_BYTES = 2 * 1024 * 1024
_TARGET_ACTIVE_TRANSCRIPT_BYTES = _ACTIVE_TRANSCRIPT_ROTATE_BYTES // 2
_TRANSCRIPT_SEGMENT_MANIFEST_VERSION = 2
_TRANSCRIPT_ACTIVE_CHUNK_ID = "active"
_TRANSCRIPT_SEGMENT_RE = re.compile(r"^\d{6}\.jsonl$")
_DEFAULT_TRANSCRIPT_PAGE_LIMIT = 160
_MAX_TRANSCRIPT_PAGE_LIMIT = 1000
_MAX_TRANSCRIPT_PAGE_RECORDS = 4_000
_MAX_TRANSCRIPT_PAGE_BYTES = 20 * 1024 * 1024
_MAX_INLINE_TRACE_DETAIL_BYTES = 32 * 1024
_MANIFEST_REBUILD_LOCKS = tuple(threading.Lock() for _ in range(32))
_ACTIVE_TRANSCRIPTS_WITH_DELTAS: set[str] = set()
_WEBUI_TURN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_WEBUI_REPLAY_IDENTITY_KEY = "_webui_replay_identity"
_WEBUI_TRACE_DETAIL_UNSAFE_KEY = "_webui_trace_detail_unsafe"
_WEBUI_TRACE_DETAIL_REF_RE = re.compile(
    r"^(?P<turn>\d{1,12})\.(?P<message>history-[0-9a-f]{20})$"
)
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
_TURN_DISPLAY_EVENTS: frozenset[str] = frozenset({
    "reasoning_delta",
    "reasoning_end",
    "delta",
    "stream_end",
    "message",
    "file_edit",
    "turn_end",
})
MAX_SESSION_MENTIONS = 8
_SESSION_MENTION_NAME_RE = re.compile(r"^[\w-]+$")
_SESSION_HANDLE_ID_RE = re.compile(r"^handle_[0-9a-f]{32}$")


def _response_sources(value: object) -> list[dict[str, str | bool]]:
    """Allow only recorded display identity, never settings or credential blobs."""
    if not isinstance(value, list):
        return []
    result: list[dict[str, str | bool]] = []
    keys = ("provider", "model", "preset")
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            return []
        fields = cast(dict[str, object], item)
        if any(not isinstance(fields.get(key), str) or not fields[key] for key in keys):
            return []
        source: dict[str, str | bool] = {key: cast(str, fields[key]) for key in keys}
        # Old records without an explicit fallback flag must not guess from model names.
        source["fallback"] = fields.get("fallback") is True
        if source not in result:
            result.append(source)
    return result


def _sanitize_turn_usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    data = cast(dict[object, object], value)
    return {
        key: item
        for key, item in data.items()
        if isinstance(key, str)
        and isinstance(item, int)
        and not isinstance(item, bool)
        and item >= 0
    }


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


def webui_transcript_revision(
    session_key: str,
    *,
    variant: Mapping[str, Any] | None = None,
) -> str | None:
    """Return a cheap revision from transcript artifact metadata and response inputs."""
    active_path = webui_transcript_path(session_key)
    segment_dir = webui_transcript_segments_dir(session_key)
    snapshots: list[tuple[str, int, int]] = []
    artifacts = (
        ("active", active_path),
        ("legacy", _legacy_webui_thread_path(session_key)),
        ("manifest", segment_dir / "manifest.json"),
        ("segments", segment_dir),
    )
    for label, path in artifacts:
        try:
            stat = path.stat()
        except OSError:
            continue
        if label != "segments" and not path.is_file():
            continue
        snapshots.append((label, stat.st_size, stat.st_mtime_ns))
    if not snapshots:
        return None

    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            snapshots,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if variant:
        digest.update(b"\0")
        digest.update(
            json.dumps(
                variant,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
    return digest.hexdigest()[:32]


class _TranscriptTurnRef(NamedTuple):
    ordinal: int
    records: list[dict[str, Any]]
    trace_details_safe: bool = True


class _TranscriptChunkRef(NamedTuple):
    chunk_id: str
    start_ordinal: int
    turn_count: int
    user_count: int


class _SessionBackfillTurn(NamedTuple):
    user_event: dict[str, Any]
    assistant_signature: tuple[str, ...]
    assistant_records: tuple[dict[str, Any], ...]


class _DeferredTraceGroup(NamedTuple):
    start: int
    stop: int
    detail_bytes: int
    trace_count: int


@dataclass(slots=True)
class TranscriptReplayStats:
    """Bounded, non-sensitive diagnostics for one history replay."""

    effective_limit: int = 0
    source_bytes: int = 0
    parsed_records: int = 0
    selected_bytes: int = 0
    selected_records: int = 0
    compacted_delta_records: int = 0
    manifest_rebuilt: bool = False
    manifest_rebuild_ms: int = 0
    replay_ms: int = 0
    capped_by_bytes: bool = False
    capped_by_records: bool = False
    truncated_oversized_turn: bool = False


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
                    lines_out.append(cast(dict[str, Any], obj))
    except OSError as e:
        logger.warning("read transcript failed {}: {}", path, e)
        return []
    return lines_out


def _records_bytes(records: list[dict[str, Any]]) -> int:
    total = 0
    for record in records:
        total += len(_record_json_line(record).encode("utf-8")) + 1
    return total


def _stream_key(record: dict[str, Any], stream: str) -> tuple[str, str, str]:
    raw_turn_id = record.get("turn_id")
    turn_id = raw_turn_id if isinstance(raw_turn_id, str) else ""
    raw_phase = record.get("turn_phase")
    phase = raw_phase if isinstance(raw_phase, str) and raw_phase else stream
    raw_stream_id = record.get("stream_id")
    stream_id = raw_stream_id if isinstance(raw_stream_id, str) else ""
    return turn_id, phase, stream_id


def _compact_completed_stream_deltas(
    turn: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Fold transport deltas into canonical end records for a completed turn."""
    if not turn or turn[-1].get("event") != "turn_end":
        return turn, 0

    pending: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = {}
    dropped_indexes: set[int] = set()
    replacements: dict[int, dict[str, Any]] = {}
    for index, record in enumerate(turn):
        event = record.get("event")
        if event in {"delta", "reasoning_delta"}:
            stream = "answer" if event == "delta" else "reasoning"
            pending.setdefault(_stream_key(record, stream), []).append((index, record))
            continue
        if event not in {"stream_end", "reasoning_end"}:
            continue
        stream = "answer" if event == "stream_end" else "reasoning"
        chunks = pending.pop(_stream_key(record, stream), [])
        if not chunks:
            continue
        completed = dict(record)
        text = completed.get("text")
        if not isinstance(text, str) or not text:
            completed["text"] = "".join(
                str(chunk.get("text") or "") for _, chunk in chunks
            )
        replacements[index] = completed
        dropped_indexes.update(chunk_index for chunk_index, _ in chunks)

    if not dropped_indexes:
        return turn, 0
    return [
        replacements.get(index, record)
        for index, record in enumerate(turn)
        if index not in dropped_indexes
    ], len(dropped_indexes)


def _compact_completed_turns(
    turns: list[list[dict[str, Any]]],
) -> tuple[list[list[dict[str, Any]]], int]:
    compacted: list[list[dict[str, Any]]] = []
    dropped = 0
    for turn in turns:
        next_turn, turn_dropped = _compact_completed_stream_deltas(turn)
        compacted.append(next_turn)
        dropped += turn_dropped
    return compacted, dropped


def _trim_oversized_turn(
    turn: list[dict[str, Any]],
    *,
    max_records: int,
    max_bytes: int,
) -> list[dict[str, Any]]:
    """Keep the useful tail of one pathological turn within a hard replay budget."""
    if not turn or max_records <= 0 or max_bytes <= 0:
        return []

    user_index = next(
        (index for index, record in enumerate(turn) if _is_user_transcript_row(record)),
        None,
    )
    end_index = next(
        (
            index
            for index in range(len(turn) - 1, -1, -1)
            if turn[index].get("event") == "turn_end"
        ),
        None,
    )
    answer_index = next(
        (
            index
            for index in range(len(turn) - 1, -1, -1)
            if turn[index].get("event") in {"delta", "stream_end", "message"}
        ),
        None,
    )
    priority = [user_index, end_index, answer_index]
    candidates = [
        *[index for index in priority if index is not None],
        *range(len(turn) - 1, -1, -1),
    ]
    selected: set[int] = set()
    selected_bytes = 0
    for index in candidates:
        if index in selected or len(selected) >= max_records:
            continue
        record_bytes = _records_bytes([turn[index]])
        if selected_bytes + record_bytes > max_bytes:
            continue
        selected.add(index)
        selected_bytes += record_bytes
    return [record for index, record in enumerate(turn) if index in selected]


def _flatten_turns(turns: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [record for turn in turns for record in turn]


def _records_with_replay_identity(
    records: list[dict[str, Any]],
    *,
    turn_ordinal: int,
    trace_details_safe: bool = True,
) -> list[dict[str, Any]]:
    return [
        {
            **record,
            _WEBUI_REPLAY_IDENTITY_KEY: f"turn:{turn_ordinal}:record:{record_index}",
            **({_WEBUI_TRACE_DETAIL_UNSAFE_KEY: True} if not trace_details_safe else {}),
        }
        for record_index, record in enumerate(records)
    ]


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


def _segment_manifest_entry(
    session_key: str,
    segment_id: str,
    *,
    stats: TranscriptReplayStats | None = None,
) -> dict[str, Any]:
    path = _segment_file_path(session_key, segment_id)
    lines = _read_transcript_file(path)
    size = path.stat().st_size if path.exists() else 0
    if stats is not None:
        stats.source_bytes += size
        stats.parsed_records += len(lines)
    return {
        "id": segment_id,
        "bytes": size,
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
    manifest_entry = cast(dict[str, Any], entry)
    segment_id = manifest_entry.get("id")
    if not isinstance(segment_id, str) or not _TRANSCRIPT_SEGMENT_RE.fullmatch(f"{segment_id}.jsonl"):
        return None
    segment_path = _segment_file_path(session_key, segment_id)
    values = {
        key: _non_negative_int(manifest_entry.get(key))
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


def _write_segment_manifest(session_key: str, entries: list[dict[str, Any]]) -> None:
    directory = webui_transcript_segments_dir(session_key)
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "version": _TRANSCRIPT_SEGMENT_MANIFEST_VERSION,
        "segments": entries,
    }
    path = _webui_transcript_manifest_path(session_key)
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _rebuild_segment_manifest(
    session_key: str,
    *,
    stats: TranscriptReplayStats | None = None,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    segment_ids = _segment_ids_on_disk(session_key)
    entries = [
        _segment_manifest_entry(session_key, segment_id, stats=stats)
        for segment_id in segment_ids
    ]
    if entries:
        _write_segment_manifest(session_key, entries)
    else:
        _webui_transcript_manifest_path(session_key).unlink(missing_ok=True)
    if stats is not None:
        stats.manifest_rebuilt = True
        stats.manifest_rebuild_ms += int((time.perf_counter() - started) * 1000)
    return entries


def _load_segment_manifest_entries(session_key: str) -> list[dict[str, Any]] | None:
    directory = webui_transcript_segments_dir(session_key)
    if not directory.is_dir():
        return []
    path = _webui_transcript_manifest_path(session_key)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        manifest = cast(dict[str, Any], data) if isinstance(data, dict) else None
        raw_segments = manifest.get("segments") if manifest is not None else None
        if (
            manifest is None
            or manifest.get("version") != _TRANSCRIPT_SEGMENT_MANIFEST_VERSION
            or not isinstance(raw_segments, list)
        ):
            return None
        entries: list[dict[str, Any]] = []
        for entry in cast(list[Any], raw_segments):
            normalized = _normalize_manifest_entry(session_key, entry)
            if normalized is None:
                return None
            entries.append(normalized)
        if [entry["id"] for entry in entries] != _segment_ids_on_disk(session_key):
            return None
        return entries
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        return None


def _manifest_rebuild_lock(session_key: str) -> threading.Lock:
    digest = hashlib.sha256(session_key.encode("utf-8")).digest()
    lock_index = int.from_bytes(digest[:2], "big") % len(_MANIFEST_REBUILD_LOCKS)
    return _MANIFEST_REBUILD_LOCKS[lock_index]


def _read_segment_manifest_entries(
    session_key: str,
    *,
    stats: TranscriptReplayStats | None = None,
) -> list[dict[str, Any]]:
    entries = _load_segment_manifest_entries(session_key)
    if entries is not None:
        return entries
    with _manifest_rebuild_lock(session_key):
        entries = _load_segment_manifest_entries(session_key)
        if entries is not None:
            return entries
        return _rebuild_segment_manifest(session_key, stats=stats)


def _repair_manifest_chunk_count(
    session_key: str,
    chunk_id: str,
    actual_turn_count: int,
    *,
    stats: TranscriptReplayStats | None = None,
) -> None:
    with _manifest_rebuild_lock(session_key):
        entries = _load_segment_manifest_entries(session_key)
        if entries is not None and any(
            entry["id"] == chunk_id and entry["turn_count"] == actual_turn_count
            for entry in entries
        ):
            return
        _rebuild_segment_manifest(session_key, stats=stats)


def _read_segment_ids(session_key: str) -> list[str]:
    return [entry["id"] for entry in _read_segment_manifest_entries(session_key)]


def _append_segment_turns(session_key: str, turns: list[list[dict[str, Any]]]) -> None:
    if not turns:
        return
    with _manifest_rebuild_lock(session_key):
        entries = _load_segment_manifest_entries(session_key)
        if entries is None:
            entries = _rebuild_segment_manifest(session_key)
        next_id = int(entries[-1]["id"]) + 1 if entries else 1
        batch: list[list[dict[str, Any]]] = []
        batch_bytes = 0

        def write_batch() -> None:
            nonlocal next_id
            segment_id = f"{next_id:06d}"
            path = _segment_file_path(session_key, segment_id)
            _write_records_to_path(path, _flatten_turns(batch))
            entries.append({
                "id": segment_id,
                "bytes": path.stat().st_size,
                "turn_count": len(batch),
                "user_count": sum(
                    1
                    for turn in batch
                    for row in turn
                    if _is_user_transcript_row(row)
                ),
            })
            next_id += 1

        for turn in turns:
            turn_bytes = _records_bytes(turn)
            if batch and batch_bytes + turn_bytes > _MAX_TRANSCRIPT_FILE_BYTES:
                write_batch()
                batch = []
                batch_bytes = 0
            batch.append(turn)
            batch_bytes += turn_bytes
        if batch:
            write_batch()
        _write_segment_manifest(session_key, entries)


def _rotate_active_transcript_if_needed(session_key: str) -> None:
    path = webui_transcript_path(session_key)
    if not path.is_file():
        return
    try:
        if path.stat().st_size <= _ACTIVE_TRANSCRIPT_ROTATE_BYTES:
            return
    except OSError:
        return

    lines = _read_transcript_file(path)
    if not lines:
        return
    turns = _split_transcript_turns(lines)
    turns, compacted_delta_records = _compact_completed_turns(turns)
    if compacted_delta_records:
        _write_records_to_path(path, _flatten_turns(turns))
        try:
            if path.stat().st_size <= _ACTIVE_TRANSCRIPT_ROTATE_BYTES:
                return
        except OSError:
            return
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


def _compact_segment_turns(
    session_key: str,
    chunk_id: str,
    *,
    stats: TranscriptReplayStats | None = None,
) -> list[list[dict[str, Any]]]:
    """Compact one immutable legacy segment and keep its manifest entry valid."""
    with _manifest_rebuild_lock(session_key):
        turns = _read_chunk_turns(session_key, chunk_id)
        if stats is not None:
            path = _segment_file_path(session_key, chunk_id)
            try:
                stats.source_bytes += path.stat().st_size
            except OSError:
                pass
            stats.parsed_records += sum(len(turn) for turn in turns)
        compacted, dropped = _compact_completed_turns(turns)
        if not dropped:
            return turns

        entries = _load_segment_manifest_entries(session_key)
        path = _segment_file_path(session_key, chunk_id)
        _write_records_to_path(path, _flatten_turns(compacted))
        if entries is None:
            _rebuild_segment_manifest(session_key, stats=stats)
        else:
            for entry in entries:
                if entry["id"] != chunk_id:
                    continue
                entry["bytes"] = path.stat().st_size
                entry["turn_count"] = len(compacted)
                entry["user_count"] = sum(
                    1
                    for turn in compacted
                    for record in turn
                    if _is_user_transcript_row(record)
                )
                break
            _write_segment_manifest(session_key, entries)
        if stats is not None:
            stats.compacted_delta_records += dropped
        return compacted


def _cached_chunk_turns(
    session_key: str,
    chunk_id: str,
    turn_cache: dict[str, list[list[dict[str, Any]]]],
    *,
    stats: TranscriptReplayStats | None = None,
) -> list[list[dict[str, Any]]]:
    if chunk_id not in turn_cache:
        if chunk_id == _TRANSCRIPT_ACTIVE_CHUNK_ID:
            path = webui_transcript_path(session_key)
        else:
            path = _segment_file_path(session_key, chunk_id)
        turns = _read_chunk_turns(session_key, chunk_id)
        needs_compaction = chunk_id != _TRANSCRIPT_ACTIVE_CHUNK_ID and any(
            record.get("event") in {"delta", "reasoning_delta"}
            for turn in turns
            for record in turn
        )
        if needs_compaction:
            turns = _compact_segment_turns(
                session_key,
                chunk_id,
                stats=stats,
            )
        elif stats is not None:
            try:
                stats.source_bytes += path.stat().st_size
            except OSError:
                pass
            stats.parsed_records += sum(len(turn) for turn in turns)
        turn_cache[chunk_id] = turns
    return turn_cache[chunk_id]


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
    cursor_data = cast(dict[str, Any], data)
    before_turn = cursor_data.get("before_turn")
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


def _chunk_turn_refs(
    session_key: str,
    turn_cache: dict[str, list[list[dict[str, Any]]]],
    *,
    stats: TranscriptReplayStats | None = None,
) -> list[_TranscriptChunkRef]:
    refs: list[_TranscriptChunkRef] = []
    ordinal = 0
    for entry in _read_segment_manifest_entries(session_key, stats=stats):
        chunk_id = str(entry["id"])
        turn_count = int(entry["turn_count"])
        if turn_count <= 0:
            continue
        refs.append(_TranscriptChunkRef(chunk_id, ordinal, turn_count, int(entry["user_count"])))
        ordinal += turn_count
    if webui_transcript_path(session_key).is_file():
        active_turns = _cached_chunk_turns(
            session_key,
            _TRANSCRIPT_ACTIVE_CHUNK_ID,
            turn_cache,
            stats=stats,
        )
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


def _transcript_turn_at_ordinal(
    session_key: str,
    ordinal: int,
) -> list[dict[str, Any]] | None:
    turn_cache: dict[str, list[list[dict[str, Any]]]] = {}
    for chunk in _chunk_turn_refs(session_key, turn_cache):
        local_index = ordinal - chunk.start_ordinal
        if local_index < 0 or local_index >= chunk.turn_count:
            continue
        turns = _cached_chunk_turns(session_key, chunk.chunk_id, turn_cache)
        return turns[local_index] if local_index < len(turns) else None
    return None


def _count_user_messages_before_ordinal(
    session_key: str,
    chunks: list[_TranscriptChunkRef],
    before_ordinal: int,
    turn_cache: dict[str, list[list[dict[str, Any]]]],
    *,
    stats: TranscriptReplayStats | None = None,
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
        turns = _cached_chunk_turns(
            session_key,
            chunk.chunk_id,
            turn_cache,
            stats=stats,
        )
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
    stats: TranscriptReplayStats | None = None,
    _manifest_rebuilt: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats = stats or TranscriptReplayStats()
    page_limit = _coerce_page_limit(limit)
    stats.effective_limit = page_limit
    turn_cache: dict[str, list[list[dict[str, Any]]]] = {}
    chunks = _chunk_turn_refs(session_key, turn_cache, stats=stats)
    total_turns = sum(chunk.turn_count for chunk in chunks)
    before_ordinal = _decode_page_cursor(before)
    upper_ordinal = total_turns if before_ordinal is None else min(before_ordinal, total_turns)
    selected: list[_TranscriptTurnRef] = []
    selected_event_count = 0
    selected_record_count = 0
    selected_bytes = 0
    budget_reached = False

    for chunk in reversed(chunks):
        if chunk.start_ordinal >= upper_ordinal:
            continue
        local_upper = min(chunk.turn_count, upper_ordinal - chunk.start_ordinal)
        if local_upper <= 0:
            continue
        turns = _cached_chunk_turns(
            session_key,
            chunk.chunk_id,
            turn_cache,
            stats=stats,
        )
        if (
            chunk.chunk_id != _TRANSCRIPT_ACTIVE_CHUNK_ID
            and len(turns) != chunk.turn_count
            and not _manifest_rebuilt
        ):
            _repair_manifest_chunk_count(
                session_key,
                chunk.chunk_id,
                len(turns),
                stats=stats,
            )
            return _select_transcript_page(
                session_key,
                limit=limit,
                before=before,
                stats=stats,
                _manifest_rebuilt=True,
            )
        local_upper = min(local_upper, len(turns))
        for turn_index in range(local_upper - 1, -1, -1):
            ordinal = chunk.start_ordinal + turn_index
            trace_details_safe = True
            turn, compacted_delta_records = _compact_completed_stream_deltas(
                turns[turn_index]
            )
            stats.compacted_delta_records += compacted_delta_records
            turn_record_count = len(turn)
            turn_bytes = _records_bytes(turn)
            exceeds_records = (
                selected_record_count + turn_record_count > _MAX_TRANSCRIPT_PAGE_RECORDS
            )
            exceeds_bytes = selected_bytes + turn_bytes > _MAX_TRANSCRIPT_PAGE_BYTES
            if exceeds_records:
                stats.capped_by_records = True
            if exceeds_bytes:
                stats.capped_by_bytes = True
            if selected and (exceeds_records or exceeds_bytes):
                budget_reached = True
                break
            if exceeds_records or exceeds_bytes:
                turn = _trim_oversized_turn(
                    turn,
                    max_records=_MAX_TRANSCRIPT_PAGE_RECORDS,
                    max_bytes=_MAX_TRANSCRIPT_PAGE_BYTES,
                )
                turn_record_count = len(turn)
                turn_bytes = _records_bytes(turn)
                stats.truncated_oversized_turn = True
                trace_details_safe = False
            selected.append(_TranscriptTurnRef(ordinal, turn, trace_details_safe))
            selected_record_count += turn_record_count
            selected_bytes += turn_bytes
            selected_event_count += _client_projection_page_event_count(turn)
            if selected_event_count >= page_limit:
                break
        if selected_event_count >= page_limit or budget_reached:
            break

    selected_chronological = list(reversed(selected))
    lines = [
        record
        for ref in selected_chronological
        for record in _records_with_replay_identity(
            ref.records,
            turn_ordinal=ref.ordinal,
            trace_details_safe=ref.trace_details_safe,
        )
    ]
    stats.selected_records = len(lines)
    stats.selected_bytes = selected_bytes
    if not selected_chronological:
        return [], {
            "before_cursor": None,
            "has_more_before": False,
            "loaded_event_count": 0,
            "user_message_offset": 0,
        }

    first_ref = selected_chronological[0]
    has_more = first_ref.ordinal > 0
    page = {
        "before_cursor": _encode_page_cursor(first_ref.ordinal) if has_more else None,
        "has_more_before": has_more,
        "loaded_event_count": 0,
        "user_message_offset": _count_user_messages_before_ordinal(
            session_key,
            chunks,
            first_ref.ordinal,
            turn_cache,
            stats=stats,
        ),
    }
    if stats.truncated_oversized_turn:
        page["truncated_oversized_turn"] = True
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


def _now_ms() -> int:
    return int(time.time() * 1000)


def _valid_created_at_ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0 and value < 10_000_000_000_000_000:
        return int(value)
    return None


def _record_for_append(obj: dict[str, Any]) -> dict[str, Any]:
    if _valid_created_at_ms(obj.get("created_at_ms")) is not None:
        return obj
    record = dict(obj)
    record["created_at_ms"] = _now_ms()
    return record


def _compact_active_completed_streams(session_key: str) -> None:
    path = webui_transcript_path(session_key)
    turns, compacted_delta_records = _compact_completed_turns(
        _split_transcript_turns(_read_transcript_file(path))
    )
    if compacted_delta_records:
        _write_records_to_path(path, _flatten_turns(turns))


def append_transcript_object(session_key: str, obj: dict[str, Any]) -> None:
    record = _record_for_append(obj)
    _append_to_active_transcript(session_key, record)
    if record.get("event") in {"delta", "reasoning_delta"}:
        _ACTIVE_TRANSCRIPTS_WITH_DELTAS.add(session_key)
    if record.get("event") == "turn_end":
        if session_key in _ACTIVE_TRANSCRIPTS_WITH_DELTAS:
            _compact_active_completed_streams(session_key)
            _ACTIVE_TRANSCRIPTS_WITH_DELTAS.discard(session_key)
        _rotate_active_transcript_if_needed(session_key)


def append_session_message_input(
    session_key: str,
    *,
    content: str,
    created_at_ms: int,
    session_message: Mapping[str, Any],
) -> None:
    """Append one admitted cross-session user input to its WebUI transcript."""
    chat_id = _chat_id_from_session_key(session_key)
    if chat_id is None:
        return
    event = build_user_transcript_event(chat_id, content)
    if event is None:
        return
    event["created_at_ms"] = created_at_ms
    event["session_message"] = dict(session_message)
    append_transcript_object(session_key, event)


def normalize_webui_turn_id(value: Any) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if _WEBUI_TURN_ID_RE.fullmatch(candidate):
            return candidate
    return str(uuid.uuid4())


def webui_message_source(metadata: dict[str, Any] | None) -> dict[str, str] | None:
    raw = (metadata or {}).get(WEBUI_MESSAGE_SOURCE_METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    source_metadata = cast(dict[str, Any], raw)
    kind = source_metadata.get("kind")
    if not isinstance(kind, str) or not is_automation_kind(kind):
        return None
    source: dict[str, str] = {"kind": kind}
    label = source_metadata.get("label")
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
        if include_source and metadata is not None and "response_sources" in metadata:
            event["response_sources"] = _response_sources(metadata["response_sources"])
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
    ) -> bool:
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
        return self.append(chat_id, record)

    def prepare_and_append_stream_event(
        self,
        chat_id: str,
        event: dict[str, Any],
        *,
        completed_text: str | None,
        metadata: dict[str, Any] | None = None,
        phase: str | None = None,
        include_source: bool = False,
    ) -> bool:
        """Annotate every live stream event, but persist only completed segments.

        Delta frames are a transport concern: retaining each token-sized chunk
        would turn rendering cadence into disk-write cadence. The matching end
        event carries the canonical segment text used by history replay.
        """
        self.prepare_event(
            chat_id,
            event,
            metadata=metadata,
            phase=phase,
            include_source=include_source,
        )
        if event.get("event") in {"delta", "reasoning_delta"}:
            return True
        record = dict(event)
        if completed_text is not None:
            record["text"] = completed_text
        return self.append(chat_id, record)

    def append_user_message(
        self,
        chat_id: str,
        text: str,
        *,
        metadata: dict[str, Any],
        media_paths: list[str] | None = None,
        cli_apps: list[dict[str, Any]] | None = None,
        mcp_presets: list[dict[str, Any]] | None = None,
        session_mentions: Sequence[Mapping[str, Any]] | None = None,
    ) -> bool:
        if text.strip() == "/stop" and not media_paths:
            return False
        payload = build_user_transcript_event(
            chat_id,
            text,
            media_paths=media_paths,
            cli_apps=cli_apps,
            mcp_presets=mcp_presets,
            session_mentions=session_mentions,
        )
        if payload is None:
            return False
        return self.prepare_and_append(chat_id, payload, metadata=metadata, phase="user")

    def append(self, chat_id: str, event: dict[str, Any]) -> bool:
        try:
            dup = json.loads(json.dumps(event, ensure_ascii=False))
            append_transcript_object(webui_session_key(chat_id), dup)
        except (OSError, ValueError, TypeError) as e:
            self._log.warning("webui transcript append failed: {}", e)
            return False
        return True

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
    chat_id = webui_chat_id(session_key)
    if chat_id is None:
        return None
    return chat_id.strip() or None


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
        if is_hidden_history_message(msg):
            continue
        msg = public_history_message(msg)
        role = msg.get("role")
        content = msg.get("content")
        text = content if isinstance(content, str) else ""
        if role == "user":
            row: dict[str, Any] = {"event": "user", "chat_id": target_chat_id, "text": text}
            media = msg.get("media")
            if isinstance(media, list) and media:
                row["media_paths"] = [
                    str(p) for p in cast(list[Any], media) if isinstance(p, str) and p
                ]
            for key in ("cli_apps", "mcp_presets", "session_mentions"):
                value = msg.get(key)
                if isinstance(value, list) and value:
                    row[key] = json.loads(json.dumps(value, ensure_ascii=False))
        elif role == "assistant" and text.strip():
            row = {"event": "message", "chat_id": target_chat_id, "text": text}
            media = msg.get("media")
            if isinstance(media, list) and media:
                row["media"] = [
                    str(p) for p in cast(list[Any], media) if isinstance(p, str) and p
                ]
        else:
            continue
        rows.append(row)
    _write_transcript_lines(target_key, rows)


def delete_webui_transcript(session_key: str) -> bool:
    _ACTIVE_TRANSCRIPTS_WITH_DELTAS.discard(session_key)
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


def normalize_session_mentions_metadata(raw: object) -> list[dict[str, str]]:
    """Validate session-reference metadata crossing a persistence seam."""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    normalized: list[dict[str, str]] = []
    for raw_item in cast(Sequence[object], raw)[:MAX_SESSION_MENTIONS]:
        if not isinstance(raw_item, Mapping):
            continue
        item = cast(Mapping[str, object], raw_item)
        name = item.get("name")
        session_key = item.get("session_key")
        title = item.get("title")
        handle_id = item.get("id")
        if not isinstance(name, str) or not isinstance(session_key, str):
            continue
        name = name.strip()[:80]
        session_key = session_key.strip()[:512]
        if not name or not session_key or _SESSION_MENTION_NAME_RE.fullmatch(name) is None:
            continue
        mention = {
            "name": name,
            "session_key": session_key,
            "title": title.strip()[:160] if isinstance(title, str) else "",
        }
        if isinstance(handle_id, str) and _SESSION_HANDLE_ID_RE.fullmatch(handle_id):
            mention["id"] = handle_id
        normalized.append(mention)
    return normalized


def normalize_session_message_ui_metadata(raw: object) -> dict[str, Any] | None:
    """Validate session-message provenance at the transcript-to-WebUI boundary."""
    if not isinstance(raw, Mapping):
        return None
    raw_data = cast(Mapping[str, object], raw)
    session = raw_data.get("session")
    message_id = raw_data.get("message_id")
    if (
        not isinstance(message_id, str)
        or not message_id.strip()
        or not isinstance(session, Mapping)
    ):
        return None
    session_data = cast(Mapping[str, object], session)
    handle_id = session_data.get("id")
    name = session_data.get("name")
    if (
        not isinstance(handle_id, str)
        or _SESSION_HANDLE_ID_RE.fullmatch(handle_id) is None
        or not isinstance(name, str)
        or not name.strip()
    ):
        return None
    handle: dict[str, Any] = {
        "id": handle_id.strip()[:128],
        "name": name.strip()[:80],
    }
    return {
        "message_id": message_id.strip()[:128],
        "session": handle,
    }


def build_user_transcript_event(
    chat_id: str,
    text: str,
    *,
    media_paths: list[Any] | None = None,
    cli_apps: list[Any] | None = None,
    mcp_presets: list[Any] | None = None,
    session_mentions: Sequence[Any] | None = None,
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
    apps = [
        dict(cast(Mapping[str, Any], app))
        for app in (cli_apps or [])
        if isinstance(app, Mapping)
    ]
    if apps:
        event["cli_apps"] = apps
    presets = [
        dict(cast(Mapping[str, Any], preset))
        for preset in (mcp_presets or [])
        if isinstance(preset, Mapping)
    ]
    if presets:
        event["mcp_presets"] = presets
    mentions = normalize_session_mentions_metadata(session_mentions)
    if mentions:
        event["session_mentions"] = mentions
    return event


def _is_legacy_raw_subagent_result(message: dict[str, Any]) -> bool:
    content = message.get("content")
    if not isinstance(content, str):
        return False
    text = content.replace("\r\n", "\n").strip()
    return (
        text.startswith("[Subagent '")
        and "\n\nTask:" in text
        and "\n\nResult:" in text
        and "Summarize this naturally" in text
    )


def _session_user_event(
    session_key: str,
    message: dict[str, Any],
) -> dict[str, Any] | None:
    if message.get("role") != "user":
        return None
    if is_hidden_history_message(message):
        return None
    message = public_history_message(message)
    if _is_legacy_raw_subagent_result(message):
        return None
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    media = message.get("media")
    cli_apps = message.get("cli_apps")
    mcp_presets = message.get("mcp_presets")
    session_mentions = message.get("session_mentions")
    chat_id = session_key.split(":", 1)[1] if ":" in session_key else session_key
    return build_user_transcript_event(
        chat_id,
        text,
        media_paths=cast(list[Any], media) if isinstance(media, list) else None,
        cli_apps=cast(list[Any], cli_apps) if isinstance(cli_apps, list) else None,
        mcp_presets=cast(list[Any], mcp_presets) if isinstance(mcp_presets, list) else None,
        session_mentions=(
            cast(list[Any], session_mentions) if isinstance(session_mentions, list) else None
        ),
    )


def _assistant_text_signature(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _session_assistant_event(
    session_key: str,
    message: dict[str, Any],
) -> dict[str, Any] | None:
    if message.get("role") != "assistant" or is_hidden_history_message(message):
        return None
    message = public_history_message(message)
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    media = message.get("media")
    media_paths = [str(path) for path in cast(list[Any], media)] if isinstance(media, list) else []
    media_paths = [path for path in media_paths if path]
    if not text.strip() and not media_paths:
        return None
    chat_id = session_key.split(":", 1)[1] if ":" in session_key else session_key
    event: dict[str, Any] = {
        "event": "message",
        "chat_id": chat_id,
        "text": text,
    }
    if media_paths:
        event["media"] = media_paths
    latency_ms = message.get("latency_ms")
    if isinstance(latency_ms, int | float) and latency_ms >= 0:
        event["latency_ms"] = int(latency_ms)
    return event


def _session_backfill_turns(
    session_key: str,
    session_messages: list[dict[str, Any]],
) -> list[_SessionBackfillTurn]:
    turns: list[_SessionBackfillTurn] = []
    current_user: dict[str, Any] | None = None
    assistant_records: list[dict[str, Any]] = []

    def flush() -> None:
        if current_user is None or not assistant_records:
            return
        signature = tuple(
            text
            for record in assistant_records
            if (text := _assistant_text_signature(record.get("text")))
        )
        turns.append(
            _SessionBackfillTurn(
                current_user,
                signature,
                tuple(dict(record) for record in assistant_records),
            )
        )

    for message in session_messages:
        role = message.get("role")
        if role == "user":
            flush()
            current_user = _session_user_event(session_key, message)
            assistant_records = []
            continue
        if role == "assistant" and current_user is not None:
            record = _session_assistant_event(session_key, message)
            if record is not None:
                assistant_records.append(record)
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


def _stable_record_digest(record: dict[str, Any]) -> str:
    persisted = {
        key: value
        for key, value in record.items()
        if key != _WEBUI_REPLAY_IDENTITY_KEY
    }
    raw = json.dumps(
        persisted,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _ensure_replay_identities(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give backfilled/recovered rows a stable identity beside persisted rows."""
    annotated: list[dict[str, Any]] = []
    for fallback_turn_index, turn in enumerate(_split_transcript_turns(lines)):
        anchor = next(
            (
                value
                for record in turn
                if isinstance(
                    value := record.get(_WEBUI_REPLAY_IDENTITY_KEY),
                    str,
                )
                and value
            ),
            None,
        )
        if anchor and ":record:" in anchor:
            turn_identity = anchor.rsplit(":record:", 1)[0]
        else:
            turn_digest = hashlib.sha256(
                "\n".join(_stable_record_digest(record) for record in turn).encode("ascii")
            ).hexdigest()[:16]
            turn_identity = f"legacy:{fallback_turn_index}:{turn_digest}"
        synthetic_occurrences: dict[str, int] = {}
        for record in turn:
            identity = record.get(_WEBUI_REPLAY_IDENTITY_KEY)
            if isinstance(identity, str) and identity:
                annotated.append(record)
                continue
            digest = _stable_record_digest(record)
            occurrence = synthetic_occurrences.get(digest, 0)
            synthetic_occurrences[digest] = occurrence + 1
            annotated.append({
                **record,
                _WEBUI_REPLAY_IDENTITY_KEY: (
                    f"{turn_identity}:synthetic:{digest}:{occurrence}"
                ),
            })
    return annotated


def _transcript_turn_signature(records: list[dict[str, Any]]) -> tuple[str, ...]:
    """Return durable assistant answer texts used only for backfill matching."""
    texts: list[str] = []
    stream_parts: list[str] = []

    def flush_stream(final_text: object = None) -> None:
        text = final_text if isinstance(final_text, str) else "".join(stream_parts)
        if signature := _assistant_text_signature(text):
            texts.append(signature)
        stream_parts.clear()

    for record in records:
        event = record.get("event")
        if event == "delta":
            chunk = record.get("text")
            if isinstance(chunk, str):
                stream_parts.append(chunk)
        elif event == "stream_end":
            final_text = record.get("text")
            if record.get("resuming") is True and record.get("merge_next") is True:
                if isinstance(final_text, str):
                    stream_parts[:] = [final_text]
                continue
            flush_stream(final_text)
        elif event == "message" and record.get("kind") not in {
            "tool_hint",
            "progress",
            "reasoning",
        }:
            flush_stream()
            if signature := _assistant_text_signature(record.get("text")):
                texts.append(signature)
        elif event in {"user", "reasoning_delta", "reasoning_end", "turn_end"}:
            flush_stream()
    flush_stream()
    return tuple(texts)


def _find_unique_session_turn(
    session_turns: list[_SessionBackfillTurn],
    signature: tuple[str, ...],
    start: int,
) -> int | None:
    if not signature:
        return None
    found: int | None = None
    for index in range(start, len(session_turns)):
        if session_turns[index].assistant_signature != signature:
            continue
        if found is not None:
            return None
        found = index
    return found


def _user_recovery_signature(event: dict[str, Any]) -> str:
    fields = {
        key: event[key]
        for key in ("text", "media_paths", "cli_apps", "mcp_presets", "session_mentions")
        if key in event
    }
    return json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _find_unique_session_turn_by_user(
    session_turns: list[_SessionBackfillTurn],
    user_event: dict[str, Any],
) -> _SessionBackfillTurn | None:
    signature = _user_recovery_signature(user_event)
    matches = [
        turn
        for turn in session_turns
        if _user_recovery_signature(turn.user_event) == signature
    ]
    return matches[0] if len(matches) == 1 else None


def _is_recoverable_answer_record(record: dict[str, Any]) -> bool:
    event = record.get("event")
    if event in {"delta", "stream_end"}:
        return True
    return event == "message" and record.get("kind") not in {
        "tool_hint",
        "progress",
        "reasoning",
    }


def _needs_incomplete_turn_recovery(lines: list[dict[str, Any]]) -> bool:
    return any(
        record.get("event") == "turn_end"
        and record.get(WEBUI_TRANSCRIPT_INCOMPLETE_KEY) is True
        for record in lines
    )


def _recover_incomplete_turns(
    lines: list[dict[str, Any]],
    session_turns: list[_SessionBackfillTurn],
) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    for turn in _split_transcript_turns(lines):
        turn_end = turn[-1] if turn else None
        if (
            not isinstance(turn_end, dict)
            or turn_end.get("event") != "turn_end"
            or turn_end.get(WEBUI_TRANSCRIPT_INCOMPLETE_KEY) is not True
        ):
            recovered.extend(turn)
            continue

        user_events = [record for record in turn if record.get("event") == "user"]
        if len(user_events) != 1:
            recovered.extend(turn)
            continue
        session_turn = _find_unique_session_turn_by_user(session_turns, user_events[0])
        if session_turn is None or not session_turn.assistant_records:
            recovered.extend(turn)
            continue

        stable_end_ms = _valid_created_at_ms(turn_end.get("created_at_ms"))
        turn_id = turn_end.get("turn_id")
        answer_records: list[dict[str, Any]] = []
        for index, source in enumerate(session_turn.assistant_records):
            answer = dict(source)
            if isinstance(turn_id, str) and turn_id:
                answer["turn_id"] = turn_id
                answer["turn_phase"] = "answer"
            if stable_end_ms is not None:
                answer["created_at_ms"] = max(
                    0,
                    stable_end_ms - len(session_turn.assistant_records) + index,
                )
            answer_records.append(answer)

        # Session history is the durable source of the completed answer. Keep
        # traces/reasoning/file edits, but replace any partial answer fragments.
        recovered.extend(
            record
            for record in turn[:-1]
            if not _is_recoverable_answer_record(record)
        )
        recovered.extend(answer_records)
        completed_end = dict(turn_end)
        completed_end.pop(WEBUI_TRANSCRIPT_INCOMPLETE_KEY, None)
        recovered.append(completed_end)
    return recovered


def _with_backfilled_user(
    records: list[dict[str, Any]],
    user_event: dict[str, Any],
) -> list[dict[str, Any]]:
    for index, rec in enumerate(records):
        if rec.get("event") in _TURN_DISPLAY_EVENTS:
            return [*records[:index], dict(user_event), *records[index:]]
    return records


def _needs_user_event_backfill(lines: list[dict[str, Any]]) -> bool:
    for turn in _split_transcript_turns(lines):
        if any(record.get("event") == "user" for record in turn):
            continue
        if _transcript_turn_signature(turn):
            return True
    return False


def _inject_missing_user_events(
    lines: list[dict[str, Any]],
    session_turns: list[_SessionBackfillTurn],
) -> list[dict[str, Any]]:
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
    call_data = cast(dict[str, Any], call)
    fn = call_data.get("function")
    function_data = cast(dict[str, Any], fn) if isinstance(fn, dict) else None
    name = function_data.get("name") if function_data is not None else None
    if not isinstance(name, str) or not name:
        raw_name = call_data.get("name")
        name = raw_name if isinstance(raw_name, str) else ""
    if not name:
        return None
    args = (
        function_data.get("arguments") if function_data is not None else None
    ) or call_data.get("arguments")
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
    for event in cast(list[Any], events):
        if not event or not isinstance(event, dict):
            continue
        tool_event = cast(dict[str, Any], event)
        if tool_event.get("phase") not in {"start", "end", "error"}:
            continue
        call_id = tool_event.get("call_id")
        if isinstance(call_id, str) and call_id:
            if call_id in seen:
                continue
            seen.add(call_id)
        t = _format_tool_call_trace(tool_event)
        if t:
            lines.append(t)
    return lines


def _normalize_tool_events(events: Any) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []
    normalized: list[dict[str, Any]] = []
    for event in cast(list[Any], events):
        if not event or not isinstance(event, dict):
            continue
        tool_event = cast(dict[str, Any], event)
        if tool_event.get("phase") not in {"start", "end", "error"}:
            continue
        if not isinstance(tool_event.get("name"), str):
            function = tool_event.get("function")
            if not isinstance(function, dict):
                continue
            typed_function = cast(dict[str, Any], function)
            if not isinstance(typed_function.get("name"), str):
                continue
        normalized.append(tool_event)
    return normalized


def _media_from_signed_urls(value: Any) -> list[dict[str, Any]]:
    media: list[dict[str, Any]] = []
    urls = cast(list[Any], value) if isinstance(value, list) else []
    for m in urls:
        if isinstance(m, dict):
            media_item = cast(dict[str, Any], m)
            if not media_item.get("url"):
                continue
            name = str(media_item.get("name") or "")
            media.append(
                {
                    "kind": _media_kind_from_name(name),
                    "url": str(media_item["url"]),
                    "name": name,
                },
            )
    return media


def _trace_detail_ref(message_id: str, record: Mapping[str, Any]) -> str | None:
    if record.get(_WEBUI_TRACE_DETAIL_UNSAFE_KEY) is True:
        return None
    identity = record.get(_WEBUI_REPLAY_IDENTITY_KEY)
    if not isinstance(identity, str):
        return None
    match = re.match(r"^turn:(\d+):record:", identity)
    return f"{match.group(1)}.{message_id}" if match else None


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[: max_bytes - 3].decode("utf-8", errors="ignore") + "…"


def _trace_summary(line: str) -> str:
    if len(line.encode("utf-8")) <= 512:
        return line
    match = re.match(r"^([A-Za-z0-9_.-]+)\(", line.strip())
    return f"{_truncate_utf8(match.group(1), 240)}(…)" if match else _truncate_utf8(line, 240)


def has_pending_tool_calls(
    lines: list[dict[str, Any]],
    *,
    active_turn_started_at: float | None = None,
    active_turn_id: str | None = None,
    active_turn_transcript_persistence_failed: bool = False,
) -> bool:
    """Return True when the selected transcript tail looks like an unfinished turn."""
    # An older canonical turn can remain unsafe even after a later turn
    # completes. Recovery removes this marker only after matching durable
    # session history, so no later turn_end may hide it.
    if any(
        rec.get(WEBUI_TRANSCRIPT_INCOMPLETE_KEY) is True
        for rec in lines
    ):
        return True
    if active_turn_started_at is not None:
        if active_turn_transcript_persistence_failed:
            return True
        if active_turn_id is None:
            return True
        for rec in reversed(lines):
            transcript_turn_id = rec.get("turn_id")
            if not isinstance(transcript_turn_id, str) or not transcript_turn_id:
                continue
            if transcript_turn_id != active_turn_id:
                return True
            return rec.get("event") != "turn_end"
        return True

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


def has_unfinished_transcript_tail(session_key: str) -> bool:
    """Return whether the active transcript ends in an unfinished turn.

    Recovery runs at gateway startup and only needs the newest, still-active
    turn. Completed turns are rotated into immutable segment files, so reading
    every historical segment here would make restart cost grow with the full
    conversation history.
    """
    return has_pending_tool_calls(
        _read_transcript_file(webui_transcript_path(session_key))
    )


def completed_turn_ids(lines: list[dict[str, Any]]) -> list[str]:
    """Return stable identities for turns with an explicitly persisted completion."""
    completed: list[str] = []
    seen: set[str] = set()
    for rec in lines:
        if (
            rec.get("event") != "turn_end"
            or rec.get(WEBUI_TRANSCRIPT_INCOMPLETE_KEY) is True
        ):
            continue
        turn_id = rec.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id or turn_id in seen:
            continue
        seen.add(turn_id)
        completed.append(turn_id)
    return completed


def build_webui_trace_detail_response(
    session_key: str,
    detail_ref: str,
) -> dict[str, Any] | None:
    """Resolve one deferred activity group as canonical projection events."""
    match = _WEBUI_TRACE_DETAIL_REF_RE.fullmatch(detail_ref)
    if match is None:
        return None
    ordinal = int(match.group("turn"))
    message_id = match.group("message")
    turn = _transcript_turn_at_ordinal(session_key, ordinal)
    if turn is None:
        return None
    turn, _ = _compact_completed_stream_deltas(turn)
    lines = _records_with_replay_identity(turn, turn_ordinal=ordinal)
    for group in _client_projection_deferred_trace_groups(lines).values():
        first = lines[group.start]
        if _client_projection_event_id(first) != message_id:
            continue
        events = [
            event
            for record in lines[group.start:group.stop]
            if (
                event := _client_projection_event(
                    record,
                    augment_user_media=None,
                    augment_assistant_media=None,
                    augment_assistant_text=None,
                )
            ) is not None
        ]
        return {"message_id": message_id, "events": events}
    return None


def _client_projection_event_id(record: Mapping[str, Any]) -> str:
    identity = record.get(_WEBUI_REPLAY_IDENTITY_KEY)
    if not isinstance(identity, str) or not identity:
        identity = _stable_record_digest(dict(record))
    digest = hashlib.sha256(f"event\0{identity}".encode("utf-8")).hexdigest()[:20]
    return f"history-{digest}"


def _client_projection_turn_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    turn_id = record.get("turn_id")
    if isinstance(turn_id, str) and turn_id:
        fields["turn_id"] = turn_id
    turn_phase = record.get("turn_phase")
    if isinstance(turn_phase, str) and turn_phase in {
        "user", "reasoning", "activity", "answer", "complete",
    }:
        fields["turn_phase"] = turn_phase
    turn_seq = record.get("turn_seq")
    if isinstance(turn_seq, int | float) and not isinstance(turn_seq, bool):
        fields["turn_seq"] = int(turn_seq)
    return fields


def _client_projection_common_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "chat_id": str(record.get("chat_id") or ""),
        "projection_id": _client_projection_event_id(record),
        **_client_projection_turn_fields(record),
    }
    created_at_ms = _valid_created_at_ms(record.get("created_at_ms"))
    if created_at_ms is not None:
        fields["created_at_ms"] = created_at_ms
    return fields


def _client_projection_source(record: dict[str, Any]) -> dict[str, Any] | None:
    source = record.get("source")
    if not isinstance(source, dict):
        return None
    source_data = cast(dict[str, Any], source)
    kind = source_data.get("kind")
    if not isinstance(kind, str) or not is_automation_kind(kind):
        return None
    projected: dict[str, Any] = {"kind": kind}
    label = source_data.get("label")
    if isinstance(label, str) and label.strip():
        projected["label"] = label.strip()
    return projected


def _client_projection_event(
    record: dict[str, Any],
    *,
    augment_user_media: Callable[[list[str]], list[dict[str, Any]]] | None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None,
    augment_assistant_text: Callable[[str], str] | None,
) -> dict[str, Any] | None:
    event = record.get("event")
    common = _client_projection_common_fields(record)
    if event in {"delta", "stream_end", "message"} and "response_sources" in record:
        common["response_sources"] = _response_sources(record["response_sources"])
    if event == "user":
        projected: dict[str, Any] = {
            "event": "user_message",
            **common,
            "text": record.get("text") if isinstance(record.get("text"), str) else "",
            "starts_turn": True,
        }
        raw_paths = record.get("media_paths")
        paths = [
            str(path)
            for path in cast(list[Any], raw_paths)
            if path
        ] if isinstance(raw_paths, list) else []
        if paths and augment_user_media is not None:
            media = augment_user_media(paths)
            if media:
                projected["media_urls"] = media
        for source_key, target_key in (
            ("cli_apps", "cli_apps"),
            ("mcp_presets", "mcp_presets"),
        ):
            value = record.get(source_key)
            if isinstance(value, list):
                rows = [
                    dict(cast(dict[str, Any], row))
                    for row in cast(list[Any], value)
                    if isinstance(row, dict)
                ]
                if rows:
                    projected[target_key] = rows
        mentions = normalize_session_mentions_metadata(record.get("session_mentions"))
        if mentions:
            projected["session_mentions"] = mentions
        session_message = normalize_session_message_ui_metadata(record.get("session_message"))
        if session_message:
            projected["provenance"] = {"session_message": session_message}
        return projected

    if event in {"delta", "stream_end", "reasoning_delta", "reasoning_end"}:
        projected = {"event": event, **common}
        text = record.get("text")
        if isinstance(text, str):
            if event == "stream_end" and augment_assistant_text is not None:
                text = augment_assistant_text(text)
            projected["text"] = text
        if event == "stream_end":
            if record.get("resuming") is True:
                projected["resuming"] = True
            if record.get("merge_next") is True:
                projected["merge_next"] = True
            source = _client_projection_source(record)
            if source:
                projected["source"] = source
        return projected

    if event == "message":
        text = record.get("text")
        content = text if isinstance(text, str) else ""
        if augment_assistant_text is not None:
            content = augment_assistant_text(content)
        projected = {"event": "message", **common, "text": content}
        kind = record.get("kind")
        if kind in {"tool_hint", "progress", "reasoning"}:
            projected["kind"] = kind
        tool_events = _normalize_tool_events(record.get("tool_events"))
        if tool_events:
            projected["tool_events"] = tool_events
        raw_media = record.get("media")
        media_paths = [
            path
            for path in cast(list[Any], raw_media)
            if isinstance(path, str) and path
        ] if isinstance(raw_media, list) else []
        media = (
            augment_assistant_media(media_paths)
            if media_paths and augment_assistant_media is not None
            else []
        )
        if not media and (not media_paths or augment_assistant_media is None):
            media = _media_from_signed_urls(record.get("media_urls"))
        if media:
            projected["media_urls"] = media
        latency_ms = record.get("latency_ms")
        if isinstance(latency_ms, int | float) and latency_ms >= 0:
            projected["latency_ms"] = int(latency_ms)
        source = _client_projection_source(record)
        if source:
            projected["source"] = source
        return projected

    if event == "file_edit":
        raw_edits = record.get("edits")
        edits = [
            dict(cast(dict[str, Any], edit))
            for edit in cast(list[Any], raw_edits)
            if isinstance(edit, dict)
        ] if isinstance(raw_edits, list) else []
        return {"event": "file_edit", **common, "edits": edits}

    if event == "context_compaction":
        compaction_id = record.get("compaction_id")
        phase = record.get("phase")
        if (
            not isinstance(compaction_id, str)
            or not compaction_id
            or not isinstance(phase, str)
            or phase not in {"started", "succeeded", "failed", "cancelled"}
        ):
            return None
        return {
            "event": "context_compaction",
            **common,
            "compaction_id": compaction_id,
            "phase": phase,
        }

    if event == "turn_end":
        projected = {"event": "turn_end", **common}
        latency_ms = record.get("latency_ms")
        if isinstance(latency_ms, int | float) and latency_ms >= 0:
            projected["latency_ms"] = int(latency_ms)
        usage = _sanitize_turn_usage(record.get("usage"))
        if usage:
            projected["usage"] = usage
        raw_round_usages = record.get("round_usages")
        if isinstance(raw_round_usages, list):
            round_usages = [
                sanitized
                for item in cast(list[object], raw_round_usages)
                if (sanitized := _sanitize_turn_usage(item)) is not None
            ]
            if round_usages:
                projected["round_usages"] = round_usages
        context_window = record.get("context_window_tokens")
        if isinstance(context_window, int | float) and context_window >= 0:
            projected["context_window_tokens"] = int(context_window)
        return projected
    return None


def _client_projection_deferred_trace_groups(
    lines: list[dict[str, Any]],
) -> dict[int, _DeferredTraceGroup]:
    """Group oversized consecutive activity events behind one stable detail ref."""
    groups: dict[int, _DeferredTraceGroup] = {}
    start: int | None = None
    detail_bytes = 0
    trace_count = 0

    def flush(stop: int) -> None:
        nonlocal start, detail_bytes, trace_count
        if (
            start is not None
            and detail_bytes > _MAX_INLINE_TRACE_DETAIL_BYTES
        ):
            groups[start] = _DeferredTraceGroup(
                start=start,
                stop=stop,
                detail_bytes=detail_bytes,
                trace_count=max(1, trace_count),
            )
        start = None
        detail_bytes = 0
        trace_count = 0

    for index, record in enumerate(lines):
        is_activity = (
            record.get("event") == "message"
            and record.get("kind") in {"tool_hint", "progress"}
        )
        if not is_activity:
            flush(index)
            continue
        event = _client_projection_event(
            record,
            augment_user_media=None,
            augment_assistant_media=None,
            augment_assistant_text=None,
        )
        if event is None:
            flush(index)
            continue
        if start is None:
            start = index
        detail_bytes += len(_record_json_line(event).encode("utf-8"))
        tool_events = _normalize_tool_events(record.get("tool_events"))
        traces = tool_trace_lines_from_events(tool_events)
        if traces:
            trace_count += len(traces)
        elif not tool_events and isinstance(record.get("text"), str) and record["text"]:
            trace_count += 1
    flush(len(lines))
    return groups


def _client_projection_page_event_count(turn: list[dict[str, Any]]) -> int:
    """Apply the soft page limit in canonical protocol events, not UI rows."""
    supported = {
        "user",
        "delta",
        "stream_end",
        "reasoning_delta",
        "reasoning_end",
        "message",
        "file_edit",
        "context_compaction",
        "turn_end",
    }
    return max(1, sum(record.get("event") in supported for record in turn))


def _client_projection_events(
    lines: list[dict[str, Any]],
    *,
    augment_user_media: Callable[[list[str]], list[dict[str, Any]]] | None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None,
    augment_assistant_text: Callable[[str], str] | None,
) -> tuple[list[dict[str, Any]], int | None]:
    events: list[dict[str, Any]] = []
    fork_boundary_event_index: int | None = None
    deferred_groups = _client_projection_deferred_trace_groups(lines)
    deferred_until = 0
    for index, record in enumerate(lines):
        if index < deferred_until:
            continue
        if record.get("event") == WEBUI_FORK_MARKER_EVENT:
            if fork_boundary_event_index is None:
                fork_boundary_event_index = len(events)
            continue
        event = _client_projection_event(
            record,
            augment_user_media=augment_user_media,
            augment_assistant_media=augment_assistant_media,
            augment_assistant_text=augment_assistant_text,
        )
        if event is None:
            continue
        group = deferred_groups.get(index)
        if group is not None:
            detail_ref = _trace_detail_ref(_client_projection_event_id(record), record)
            last_text = next(
                (
                    text
                    for grouped in reversed(lines[group.start:group.stop])
                    if isinstance((text := grouped.get("text")), str) and text
                ),
                "",
            )
            event["text"] = _trace_summary(last_text)
            event.pop("tool_events", None)
            if detail_ref is not None:
                event["trace_detail"] = {
                    "ref": detail_ref,
                    "bytes": group.detail_bytes,
                    "traceCount": group.trace_count,
                }
            deferred_until = group.stop
        events.append(event)
    return events, fork_boundary_event_index


def build_webui_thread_response(
    session_key: str,
    *,
    augment_user_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_text: Callable[[str], str] | None = None,
    session_messages: list[dict[str, Any]] | None = None,
    session_messages_loader: Callable[[], list[dict[str, Any]] | None] | None = None,
    active_turn_started_at: float | None = None,
    active_turn_id: str | None = None,
    active_turn_transcript_persistence_failed: bool = False,
    limit: int | None = None,
    direction: str | None = None,
    before: str | None = None,
    stats: TranscriptReplayStats | None = None,
) -> dict[str, Any] | None:
    """Return canonical transcript events for the WebUI projector."""
    replay_stats = stats or TranscriptReplayStats()
    lines, page = _select_transcript_page(
        session_key,
        limit=limit,
        before=before,
        stats=replay_stats,
    )
    if not lines and active_turn_started_at is None:
        return None
    needs_user_backfill = _needs_user_event_backfill(lines)
    needs_incomplete_recovery = _needs_incomplete_turn_recovery(lines)
    if (
        session_messages is None
        and session_messages_loader is not None
        and (needs_user_backfill or needs_incomplete_recovery)
    ):
        session_messages = session_messages_loader()
    if session_messages and (needs_user_backfill or needs_incomplete_recovery):
        session_turns = _session_backfill_turns(session_key, session_messages)
        if needs_user_backfill:
            lines = _inject_missing_user_events(lines, session_turns)
        if needs_incomplete_recovery:
            lines = _recover_incomplete_turns(lines, session_turns)
    lines = _ensure_replay_identities(lines)
    payload: dict[str, Any] = {
        "schemaVersion": WEBUI_TRANSCRIPT_SCHEMA_VERSION,
        "sessionKey": session_key,
        "completed_turn_ids": completed_turn_ids(lines),
        "has_pending_tool_calls": has_pending_tool_calls(
            lines,
            active_turn_started_at=active_turn_started_at,
            active_turn_id=active_turn_id,
            active_turn_transcript_persistence_failed=(
                active_turn_transcript_persistence_failed
            ),
        ),
        "active_turn_id": active_turn_id,
    }
    replay_started = time.perf_counter()
    events, fork_boundary_event_index = _client_projection_events(
        lines,
        augment_user_media=augment_user_media,
        augment_assistant_media=augment_assistant_media,
        augment_assistant_text=augment_assistant_text,
    )
    replay_stats.replay_ms += int((time.perf_counter() - replay_started) * 1000)
    payload["projection"] = "events"
    payload["events"] = events
    page["loaded_event_count"] = len(events)
    if fork_boundary_event_index is not None:
        payload["fork_boundary_event_index"] = fork_boundary_event_index
    payload["page"] = page
    return payload
