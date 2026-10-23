"""WebUI history projection over durable SQLite session facts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, NotRequired, Sequence, TypedDict, cast
from urllib.parse import unquote, urlparse

from loguru import logger

from nanobot.bus.events import INBOUND_META_LOCAL_MEDIA, INBOUND_META_TURN_ID
from nanobot.runtime_context import public_history_message
from nanobot.session.automation_turns import is_automation_kind
from nanobot.session.display_history import (
    HISTORY_GENERATION_METADATA_KEY,
    HistoryFact,
    HistoryReader,
)
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import Session, SessionManager
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.session.state import SessionOperationQueueFullError
from nanobot.webui.history import (
    fact_from_record,
    initialize_history,
    record_from_fact,
    turn_records,
)
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY
from nanobot.webui.outbound_wire import project_tool_events
from nanobot.webui.session_identity import webui_chat_id, webui_session_key

WEBUI_TRANSCRIPT_SCHEMA_VERSION = 3
WEBUI_FORK_MARKER_EVENT = "fork_marker"
WEBUI_TRANSCRIPT_INCOMPLETE_KEY = "transcript_incomplete"
_DEFAULT_TRANSCRIPT_PAGE_LIMIT = 160
_MAX_TRANSCRIPT_PAGE_LIMIT = 1000
_MAX_TRANSCRIPT_PAGE_RECORDS = 4_000
_MAX_TRANSCRIPT_PAGE_BYTES = 20 * 1024 * 1024
_MAX_INLINE_TRACE_DETAIL_BYTES = 32 * 1024
_WEBUI_TURN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_WEBUI_REPLAY_IDENTITY_KEY = "_webui_replay_identity"
_WEBUI_PROJECTION_RECEIPTS_KEY = "_webui_projection_receipts"
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


def webui_transcript_revision(
    session_key: str, *, history: HistoryReader, variant: Mapping[str, Any] | None = None,
) -> str | None:
    revision = history.revision
    if revision is None:
        return None
    encoded = json.dumps((revision, variant), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


class _TranscriptTurnRef(NamedTuple):
    ordinal: int
    records: list[dict[str, Any]]
    trace_details_safe: bool = True


class _SessionBackfillTurn(NamedTuple):
    user_event: dict[str, Any]
    assistant_signature: tuple[str, ...]
    assistant_records: tuple[dict[str, Any], ...]


class _ProjectionReceipt(TypedDict):
    turn_id: str
    ranges: list[list[int]]


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
    replay_ms: int = 0
    capped_by_bytes: bool = False
    capped_by_records: bool = False
    truncated_oversized_turn: bool = False


def _record_json_line(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


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


def _projection_receipts(records: Sequence[Mapping[str, Any]]) -> list[_ProjectionReceipt]:
    """Compress actual represented facts by turn, without covering missing sequences."""
    members: dict[str, set[int]] = {}
    for record in records:
        turn_id, sequence = record.get("turn_id"), record.get("turn_seq")
        if (
            isinstance(turn_id, str) and turn_id
            and isinstance(sequence, int) and not isinstance(sequence, bool) and sequence >= 0
        ):
            members.setdefault(turn_id, set()).add(sequence)
    receipts: list[_ProjectionReceipt] = []
    for turn_id, sequences in members.items():
        ranges: list[list[int]] = []
        for sequence in sorted(sequences):
            if ranges and ranges[-1][1] + 1 == sequence:
                ranges[-1][1] = sequence
            else:
                ranges.append([sequence, sequence])
        receipts.append({"turn_id": turn_id, "ranges": ranges})
    return receipts


def _compact_completed_stream_deltas(
    turn: list[dict[str, Any]],
    *,
    include_projection_receipts: bool = False,
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
        if include_projection_receipts:
            receipts = _projection_receipts([*(chunk for _, chunk in chunks), record])
            if receipts:
                completed[_WEBUI_PROJECTION_RECEIPTS_KEY] = receipts
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




def compact_legacy_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns, _ = _compact_completed_turns(_split_transcript_turns(records))
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
            _WEBUI_REPLAY_IDENTITY_KEY: record.get(_WEBUI_REPLAY_IDENTITY_KEY, f"turn:{turn_ordinal}:record:{record_index}"),
            **({_WEBUI_TRACE_DETAIL_UNSAFE_KEY: True} if not trace_details_safe else {}),
        }
        for record_index, record in enumerate(records)
    ]


def _encode_page_cursor(before_turn_ordinal: int) -> str:
    raw = json.dumps(
        {"before_turn": before_turn_ordinal},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_transcript_cursor(value: str | None) -> int | None:
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


def _transcript_turn_at_ordinal(
    session_key: str, ordinal: int, *, history: HistoryReader,
) -> list[dict[str, Any]] | None:
    return turn_records(history, ordinal) or None


def _select_transcript_page(
    session_key: str, *, history: HistoryReader, limit: int | None,
    before: str | None, after: str | None = None, stats: TranscriptReplayStats | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats = stats or TranscriptReplayStats()
    page_limit = _coerce_page_limit(limit)
    stats.effective_limit = page_limit
    total_turns = history.turn_count
    before_ordinal = decode_transcript_cursor(before)
    upper = total_turns if before_ordinal is None else min(before_ordinal, total_turns)
    after_ordinal = decode_transcript_cursor(after)
    selected: list[_TranscriptTurnRef] = []
    event_count = record_count = byte_count = 0
    for ref in history.turns(before=upper, after=after_ordinal or 0, reverse=after_ordinal is None):
        exceeds_records = record_count + ref.record_count > _MAX_TRANSCRIPT_PAGE_RECORDS
        exceeds_bytes = byte_count + ref.byte_count > _MAX_TRANSCRIPT_PAGE_BYTES
        stats.capped_by_records |= exceeds_records
        stats.capped_by_bytes |= exceeds_bytes
        if selected and (exceeds_records or exceeds_bytes):
            break
        safe = not (exceeds_records or exceeds_bytes)
        turn = turn_records(
            history, ref.ordinal,
            max_records=None if safe else _MAX_TRANSCRIPT_PAGE_RECORDS,
            max_bytes=None if safe else _MAX_TRANSCRIPT_PAGE_BYTES,
        )
        stats.parsed_records += len(turn)
        stats.source_bytes += ref.byte_count if safe else _records_bytes(turn)
        turn, dropped = _compact_completed_stream_deltas(turn, include_projection_receipts=True)
        stats.compacted_delta_records += dropped
        if not safe:
            stats.truncated_oversized_turn = True
        selected.append(_TranscriptTurnRef(ref.ordinal, turn, safe))
        record_count += len(turn)
        byte_count += _records_bytes(turn)
        event_count += _client_projection_page_event_count(turn)
        if event_count >= page_limit:
            break
    chronological = selected if after_ordinal is not None else list(reversed(selected))
    records = [record for ref in chronological for record in _records_with_replay_identity(
        ref.records, turn_ordinal=ref.ordinal, trace_details_safe=ref.trace_details_safe,
    )]
    stats.selected_records, stats.selected_bytes = len(records), byte_count
    if not chronological:
        return [], {"before_cursor": None, "has_more_before": False, "after_cursor": None,
                    "has_more_after": False, "loaded_event_count": 0, "user_message_offset": 0}
    first, last = chronological[0].ordinal, chronological[-1].ordinal
    page: dict[str, Any] = {
        "before_cursor": _encode_page_cursor(first) if first else None,
        "has_more_before": first > 0,
        "after_cursor": _encode_page_cursor(last + 1) if last + 1 < total_turns else None,
        "has_more_after": last + 1 < total_turns, "loaded_event_count": 0,
        "user_message_offset": history.user_count_before(first),
    }
    if stats.truncated_oversized_turn:
        page["truncated_oversized_turn"] = True
    return records, page


def read_transcript_lines(session_key: str, *, history: HistoryReader) -> list[dict[str, Any]]:
    return [record_from_fact(fact, session_key) for fact in history.all_facts()]


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


def append_transcript_object(
    session_key: str, obj: dict[str, Any], *, sessions: SessionManager,
) -> None:
    """Offline import/fixture helper; runtime writes through the async recorder."""
    sessions.append_history(session_key, [fact_from_record(_record_for_append(obj))])


async def append_session_message_input(
    session_key: str, *, sessions: SessionManager, content: str, created_at_ms: int,
    session_message: Mapping[str, Any],
) -> None:
    chat_id = _chat_id_from_session_key(session_key)
    if chat_id is None:
        return
    event = build_user_transcript_event(chat_id, content)
    if event is None:
        return
    event.update(created_at_ms=created_at_ms, session_message=dict(session_message))
    await sessions.state.append_history(session_key, [fact_from_record(event)],
                                         expected_generation=None)


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
    """Capture channel facts through the session owner before transport fan-out."""

    def __init__(self, sessions: SessionManager | None, log: Any = logger) -> None:
        self.sessions = sessions
        self._log = log
        self._turn_sequences: dict[tuple[str, str], int] = {}

    async def initialize(self) -> None:
        sessions = self.sessions
        if sessions is not None:
            await initialize_history(sessions)

    def client_turn_metadata(self, value: Any) -> dict[str, str]:
        return {WEBUI_TURN_METADATA_KEY: normalize_webui_turn_id(value)}

    def prepare_event(
        self, chat_id: str, event: dict[str, Any], *, metadata: dict[str, Any] | None = None,
        phase: str | None = None, include_source: bool = False,
    ) -> None:
        if include_source and (source := webui_message_source(metadata)):
            event["source"] = source
        if include_source and metadata is not None and "response_sources" in metadata:
            event["response_sources"] = _response_sources(metadata["response_sources"])
        self._annotate_turn(chat_id, event, metadata, phase)

    async def prepare_and_append(
        self, chat_id: str, event: dict[str, Any], *, metadata: dict[str, Any] | None = None,
        phase: str | None = None, include_source: bool = False,
        transcript_overrides: dict[str, Any] | None = None,
    ) -> bool:
        self.prepare_event(chat_id, event, metadata=metadata, phase=phase, include_source=include_source)
        record = {**event, **(transcript_overrides or {})}
        return await self.append(chat_id, record, metadata=metadata)

    async def prepare_and_append_stream_event(
        self, chat_id: str, event: dict[str, Any], *, completed_text: str | None,
        metadata: dict[str, Any] | None = None, phase: str | None = None, include_source: bool = False,
    ) -> bool:
        self.prepare_event(chat_id, event, metadata=metadata, phase=phase, include_source=include_source)
        if event.get("event") in {"delta", "reasoning_delta"}:
            return True
        record = dict(event)
        if completed_text is not None:
            record["text"] = completed_text
        return await self.append(chat_id, record, metadata=metadata)

    async def append_user_message(
        self, chat_id: str, text: str, *, metadata: dict[str, Any],
        media_paths: list[str] | None = None, cli_apps: list[dict[str, Any]] | None = None,
        mcp_presets: list[dict[str, Any]] | None = None,
        session_mentions: Sequence[Mapping[str, Any]] | None = None,
    ) -> bool:
        if text.strip() == "/stop" and not media_paths:
            return False
        event = build_user_transcript_event(
            chat_id,
            text,
            media_paths=media_paths,
            local_media_paths=_local_media_paths(metadata),
            cli_apps=cli_apps,
            mcp_presets=mcp_presets,
            session_mentions=session_mentions,
        )
        if event is None:
            return False
        return await self.prepare_and_append(chat_id, event, metadata=metadata, phase="user")

    async def append(
        self, chat_id: str, event: dict[str, Any], *, metadata: dict[str, Any] | None,
    ) -> bool:
        if self.sessions is None:
            return True  # A transport-only channel has no durable session service.
        generation = (metadata or {}).get(HISTORY_GENERATION_METADATA_KEY)
        if not isinstance(generation, str) or not generation:
            self._log.warning("history event has no admitted generation for {}", chat_id)
            return False
        try:
            fact = fact_from_record(_record_for_append(event))
            await self.sessions.state.append_history(webui_session_key(chat_id), [fact],
                                                     expected_generation=generation)
        except (OSError, ValueError, TypeError, sqlite3.Error, SessionConflictError, SessionOperationQueueFullError) as exc:
            self._log.warning("history append failed for {}: {}", chat_id, exc)
            return False
        return True

    def _next_turn_seq(self, chat_id: str, turn_id: str) -> int:
        key = (chat_id, turn_id)
        sequence = self._turn_sequences.get(key, 0) + 1
        self._turn_sequences[key] = sequence
        return sequence

    def _annotate_turn(
        self, chat_id: str, event: dict[str, Any], metadata: dict[str, Any] | None,
        phase: str | None,
    ) -> None:
        turn_id = (metadata or {}).get(WEBUI_TURN_METADATA_KEY)
        if phase is None or not isinstance(turn_id, str) or not turn_id:
            return
        event.update(turn_id=turn_id, turn_phase=phase, turn_seq=self._next_turn_seq(chat_id, turn_id))
        if phase == "complete":
            self._turn_sequences.pop((chat_id, turn_id), None)


def _chat_id_from_session_key(session_key: str) -> str | None:
    chat_id = webui_chat_id(session_key)
    if chat_id is None:
        return None
    return chat_id.strip() or None


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


def _local_media_paths(record: Mapping[str, Any]) -> list[str]:
    raw = record.get(INBOUND_META_LOCAL_MEDIA)
    return [path for path in cast(list[object], raw) if isinstance(path, str)] if isinstance(raw, list) else []


def build_user_transcript_event(
    chat_id: str,
    text: str,
    *,
    media_paths: list[Any] | None = None,
    local_media_paths: list[str] | None = None,
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
        local = [path for path in (local_media_paths or []) if path in paths]
        if local:
            event[INBOUND_META_LOCAL_MEDIA] = local
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
    *,
    canonical_position: int | None = None,
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
    event = build_user_transcript_event(
        chat_id,
        text,
        media_paths=cast(list[Any], media) if isinstance(media, list) else None,
        local_media_paths=_local_media_paths(message),
        cli_apps=cast(list[Any], cli_apps) if isinstance(cli_apps, list) else None,
        mcp_presets=cast(list[Any], mcp_presets) if isinstance(mcp_presets, list) else None,
        session_mentions=(
            cast(list[Any], session_mentions) if isinstance(session_mentions, list) else None
        ),
    )
    if event is None:
        return None
    timestamp = message.get("timestamp")
    created_at_ms = None
    if isinstance(timestamp, str):
        try:
            created_at_ms = _valid_created_at_ms(datetime.fromisoformat(timestamp).timestamp() * 1000)
        except (ValueError, OverflowError, OSError):
            pass
    event["created_at_ms"] = created_at_ms if created_at_ms is not None else 0
    provenance = normalize_session_message_ui_metadata(message.get("session_message"))
    if provenance:
        event["session_message"] = provenance
    input_id = message.get(INBOUND_META_TURN_ID)
    if isinstance(input_id, str) and _WEBUI_TURN_ID_RE.fullmatch(input_id):
        event["turn_id"] = input_id
        event["turn_phase"] = "user"
        event[_WEBUI_REPLAY_IDENTITY_KEY] = f"input:{session_key}:{input_id}"
    elif canonical_position is not None:
        event[_WEBUI_REPLAY_IDENTITY_KEY] = f"canonical:{session_key}:message:{canonical_position}"
    return event


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


def session_display_facts(session: Session) -> list[HistoryFact]:
    """Basic projection for a fork whose source has model records but no display facts."""
    return [fact_from_record(row) for message in session.messages
            if (row := _session_user_event(session.key, message)
                or _session_assistant_event(session.key, message)) is not None]


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

    for position, message in enumerate(session_messages):
        role = message.get("role")
        if role == "user":
            flush()
            current_user = _session_user_event(session_key, message, canonical_position=position)
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


def _user_recovery_signature(event: dict[str, Any]) -> str:
    fields = {
        key: event[key]
        for key in ("text", "media_paths", INBOUND_META_LOCAL_MEDIA, "cli_apps", "mcp_presets", "session_mentions", "session_message")
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


def _needs_user_event_backfill(lines: list[dict[str, Any]]) -> bool:
    return any(
        not any(record.get("event") == "user" for record in turn)
        and _transcript_turn_signature(turn)
        for turn in _split_transcript_turns(lines)
    )


def _with_backfilled_user(
    records: list[dict[str, Any]],
    user_event: dict[str, Any],
) -> list[dict[str, Any]]:
    for index, rec in enumerate(records):
        if rec.get("event") in _TURN_DISPLAY_EVENTS:
            return [*records[:index], dict(user_event), *records[index:]]
    return records


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


def has_unfinished_transcript_tail(session_key: str, *, history: HistoryReader) -> bool:
    count = history.turn_count
    return bool(count and has_pending_tool_calls(turn_records(history, count - 1)))


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
    *, history: HistoryReader,
) -> dict[str, Any] | None:
    """Resolve one deferred activity group as canonical projection events."""
    match = _WEBUI_TRACE_DETAIL_REF_RE.fullmatch(detail_ref)
    if match is None:
        return None
    ordinal = int(match.group("turn"))
    message_id = match.group("message")
    turn = _transcript_turn_at_ordinal(session_key, ordinal, history=history)
    if turn is None:
        return None
    turn, _ = _compact_completed_stream_deltas(turn, include_projection_receipts=True)
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
    receipts = record.get(_WEBUI_PROJECTION_RECEIPTS_KEY)
    if receipts:
        fields["projection_receipts"] = receipts
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
    augment_user_media: Callable[[list[str], list[str]], list[dict[str, Any]]] | None,
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
            media = augment_user_media(paths, _local_media_paths(record))
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
        stream_id = record.get("stream_id")
        if isinstance(stream_id, str) and stream_id:
            projected["stream_id"] = stream_id
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
        projected = {
            "event": "context_compaction",
            **common,
            "compaction_id": compaction_id,
            "phase": phase,
        }
        reason = record.get("reason")
        if isinstance(reason, str) and reason in {"idle", "context_pressure", "manual", "provider_native"}:
            projected["reason"] = reason
        return projected

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
        for key in ("outcome", "failure_kind", "failure_error_kind", "failure_message"):
            if isinstance(value := record.get(key), str):
                projected[key] = value
        if isinstance(attempts := record.get("failure_attempts"), int) and not isinstance(attempts, bool):
            projected["failure_attempts"] = attempts
        if isinstance(goal := record.get("goal_state"), dict):
            projected["goal_state"] = goal
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
    augment_user_media: Callable[[list[str], list[str]], list[dict[str, Any]]] | None,
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
            receipts = _projection_receipts(lines[group.start:group.stop])
            if receipts:
                event["projection_receipts"] = receipts
            if detail_ref is not None:
                event["trace_detail"] = {
                    "ref": detail_ref,
                    "bytes": group.detail_bytes,
                    "traceCount": group.trace_count,
                }
            deferred_until = group.stop
        events.append(event)
    return events, fork_boundary_event_index


def build_session_thread_response(
    session: Session,
    *,
    active: bool = False,
    latency_ms: int | None = None,
    augment_user_media: Callable[[list[str], list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_text: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Project a Session snapshot without creating a second display transcript."""
    rows: list[dict[str, Any]] = []
    chat_id = session.key.split(":", 1)[-1]
    turn_id = f"session:{session.key}:0"
    created_at_ms = int(session.created_at.timestamp() * 1000)
    for index, message in enumerate(session.messages):
        if is_hidden_history_message(message):
            continue
        if message.get("role") == "user":
            turn_id = f"session:{session.key}:{index}"
        timestamp = message.get("timestamp")
        if isinstance(timestamp, str):
            try:
                created_at_ms = int(datetime.fromisoformat(timestamp).timestamp() * 1000)
            except ValueError:
                pass
        records: list[dict[str, Any]] = []
        row = _session_user_event(session.key, message) or _session_assistant_event(session.key, message)
        reasoning = message.get("reasoning_content")
        if message.get("role") == "assistant" and isinstance(reasoning, str) and reasoning:
            records.append({"event": "message", "text": reasoning, "kind": "reasoning"})
        calls = message.get("tool_calls")
        has_calls = isinstance(calls, list) and len(cast(list[object], calls)) > 0
        if row is not None and has_calls:
            row["kind"] = "progress"
            records.append(row)
        if message.get("role") == "assistant":
            tools = project_tool_events(_normalize_tool_events(message.get("tool_events")))
            if tools:
                records.append({"event": "message", "kind": "tool_hint",
                                "text": "\n".join(tool_trace_lines_from_events(tools)),
                                "tool_events": tools})
            edits = message.get("file_edit_events")
            if isinstance(edits, list) and edits:
                records.append({"event": "file_edit", "edits": edits})
        if row is not None and not has_calls:
            records.append(row)
        for offset, record in enumerate(records):
            record.update({
                "chat_id": chat_id, "turn_id": turn_id,
                "turn_phase": "user" if record["event"] == "user" else
                    "reasoning" if record.get("kind") == "reasoning" else
                    "activity" if record["event"] == "file_edit" or record.get("kind") in {"progress", "tool_hint"}
                    else "answer",
                "created_at_ms": created_at_ms,
                _WEBUI_REPLAY_IDENTITY_KEY: f"session:{session.key}:{index}:{offset}",
            })
            rows.append(record)
    if not active and rows:
        rows.append({"event": "turn_end", "chat_id": chat_id,
                     "turn_id": turn_id, "latency_ms": latency_ms,
                     _WEBUI_REPLAY_IDENTITY_KEY: f"session:{session.key}:end"})
    events = [event for record in rows if (event := _client_projection_event(
        record, augment_user_media=augment_user_media, augment_assistant_media=augment_assistant_media,
        augment_assistant_text=augment_assistant_text,
    )) is not None]
    return {"schemaVersion": WEBUI_TRANSCRIPT_SCHEMA_VERSION, "sessionKey": session.key,
            "projection": "events", "events": events,
            "active_turn_id": turn_id if active else None}


def build_webui_thread_response(
    session_key: str,
    *,
    history: HistoryReader,
    augment_user_media: Callable[[list[str], list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    augment_assistant_text: Callable[[str], str] | None = None,
    session_messages: list[dict[str, Any]] | None = None,
    session_messages_loader: Callable[[], list[dict[str, Any]] | None] | None = None,
    session_version_loader: Callable[[], tuple[str, int] | None] | None = None,
    active_turn_started_at: float | None = None,
    active_turn_id: str | None = None,
    active_turn_transcript_persistence_failed: bool = False,
    limit: int | None = None,
    direction: str | None = None,
    before: str | None = None,
    after: str | None = None,
    stats: TranscriptReplayStats | None = None,
) -> dict[str, Any] | None:
    """Return canonical transcript events for the WebUI projector."""
    replay_stats = stats or TranscriptReplayStats()
    lines, page = _select_transcript_page(
        session_key,
        history=history,
        limit=limit,
        before=before,
        after=after,
        stats=replay_stats,
    )
    if not lines and active_turn_started_at is None:
        return None
    session_turns: list[_SessionBackfillTurn] | None = None

    def load_session_turns() -> list[_SessionBackfillTurn]:
        nonlocal session_messages, session_turns
        if session_turns is None:
            if session_messages is None and session_messages_loader is not None:
                session_messages = session_messages_loader()
            session_turns = _session_backfill_turns(session_key, session_messages or [])
        return session_turns

    if _needs_user_event_backfill(lines):
        view, _ = _prompt_view_snapshot(
            session_key, history=history, session_turns_loader=load_session_turns,
            session_version_loader=session_version_loader,
        )
        recovered_lines: list[dict[str, Any]] = []
        selected_turns = _split_transcript_turns(lines)
        for turn in selected_turns:
            # Page selection assigns this absolute identity before any recovery.
            ordinal = int(turn[0][_WEBUI_REPLAY_IDENTITY_KEY].split(":")[1])
            user = view.backfilled_users.get(ordinal)
            recovered_lines.extend(_with_backfilled_user(turn, user) if user is not None else turn)
        lines = recovered_lines
    if _needs_incomplete_turn_recovery(lines):
        lines = _recover_incomplete_turns(lines, load_session_turns())
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


class PromptSummary(TypedDict):
    id: str
    preview: str
    answerPreview: str
    createdAt: int
    cursor: str
    turnId: str


class _BackfillCandidate(NamedTuple):
    ordinal: int
    signature: str
    answer_preview: str
    has_user: bool


class _ChunkPromptView(NamedTuple):
    prompts: tuple[PromptSummary, ...]
    candidates: tuple[_BackfillCandidate, ...]


class _PromptView(NamedTuple):
    prompts: tuple[PromptSummary, ...]
    backfilled_users: dict[int, dict[str, Any]]
    needs_canonical: bool


def _assistant_signature_identity(signature: tuple[str, ...]) -> str:
    if not signature:
        return ""
    return hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode("utf-8")).hexdigest()


def prompt_index_revision(session_key: str, session_version: tuple[str, int] | None = None, *, history: HistoryReader) -> str | None:
    """Validate display inputs without reading canonical history or constructing a view."""
    return webui_transcript_revision(session_key, history=history, variant={"session_version": session_version})


def _prompt_summary(record: dict[str, Any], ordinal: int, answer: str) -> PromptSummary:
    return {
        "id": _client_projection_event_id(record),
        "preview": str(record.get("text") or "").strip()[:320],
        "answerPreview": answer,
        "createdAt": _valid_created_at_ms(record.get("created_at_ms")) or 0,
        "cursor": _encode_page_cursor(ordinal),
        "turnId": str(record.get("turn_id") or ""),
    }


def _history_prompt_summaries(history: HistoryReader) -> _ChunkPromptView:
    result: list[PromptSummary] = []
    candidates: list[_BackfillCandidate] = []
    turns: dict[int, list[dict[str, Any]]] = {}
    for ordinal, position, fact in history.navigation():
        record = record_from_fact(fact, history.key)
        record[_WEBUI_REPLAY_IDENTITY_KEY] = f"turn:{ordinal}:record:{position}"
        turns.setdefault(ordinal, []).append(record)
    for ordinal, records in turns.items():
        has_user = any(record.get("event") == "user" for record in records)
        signature = _transcript_turn_signature(records)
        candidates.append(_BackfillCandidate(ordinal, _assistant_signature_identity(signature),
                                             signature[0][:240] if signature else "", has_user))
        seen_turns: set[str] = set()
        seen_messages: set[str] = set()
        for index, record in enumerate(records):
            if record.get("event") != "user":
                continue
            turn_id = str(record.get("turn_id") or "")
            provenance = normalize_session_message_ui_metadata(record.get("session_message"))
            if provenance:
                message_id = str(provenance["message_id"])
                if message_id in seen_messages:
                    continue
                seen_messages.add(message_id)
            elif turn_id and turn_id in seen_turns:
                continue
            if turn_id:
                seen_turns.add(turn_id)
            answer = ""
            for following in records[index + 1:]:
                if following.get("event") == "user":
                    break
                if following.get("event") in {"message", "stream_end"} and not following.get("kind"):
                    answer = str(following.get("text") or "").strip()[:240]
                    if answer:
                        break
            result.append(_prompt_summary(record, ordinal, answer))
    return _ChunkPromptView(tuple(result), tuple(candidates))


def _build_prompt_view(
    session_key: str,
    *,
    history: HistoryReader,
    session_turns_loader: Callable[[], list[_SessionBackfillTurn]] | None = None,
) -> _PromptView:
    chunk = _history_prompt_summaries(history)
    raw_prompts = list(chunk.prompts)
    candidates = list(chunk.candidates)
    session_turns = None
    needs_canonical = any(not candidate.has_user and candidate.signature for candidate in candidates)
    if needs_canonical and session_turns_loader is not None:
        session_turns = session_turns_loader()
    entries: list[tuple[int, PromptSummary, dict[str, Any] | None]] = [
        (decode_transcript_cursor(prompt["cursor"]) or 0, prompt, None) for prompt in raw_prompts
    ]
    session_cursor = 0
    signature_positions: dict[str, list[int]] = {}
    for position, turn in enumerate(session_turns or []):
        signature_positions.setdefault(_assistant_signature_identity(turn.assistant_signature), []).append(position)
    for candidate in candidates:
        if not session_turns:
            break
        positions = signature_positions.get(candidate.signature)
        if not candidate.signature or not positions:
            continue
        # Preserve unique-in-suffix matching without rescanning canonical history
        # for each transcript turn. Ambiguous answers still cannot backfill a user.
        offset = bisect_left(positions, session_cursor)
        if offset != len(positions) - 1:
            continue
        match = positions[offset]
        session_cursor = match + 1
        if candidate.has_user:
            continue
        user = dict(session_turns[match].user_event)
        summary = _prompt_summary(user, candidate.ordinal, candidate.answer_preview)
        entries.append((candidate.ordinal, summary, user))
    prompts: list[PromptSummary] = []
    backfilled_users: dict[int, dict[str, Any]] = {}
    for ordinal, prompt, user in sorted(entries, key=lambda entry: entry[0]):
        prompts.append(prompt)
        if user is not None:
            backfilled_users[ordinal] = user
    return _PromptView(tuple(prompts), backfilled_users, needs_canonical)


def build_prompt_index(
    session_key: str,
    *,
    history: HistoryReader,
    session_messages_loader: Callable[[], list[dict[str, Any]] | None] | None = None,
) -> list[PromptSummary]:
    """Read the display prompt directory; only missing-user turns load canonical history."""
    view, _ = _prompt_view_snapshot(
        session_key,
        history=history,
        session_turns_loader=lambda: _session_backfill_turns(
            session_key, (session_messages_loader() if session_messages_loader else None) or [],
        ),
    )
    return list(view.prompts)


# Bounded navigation snapshots retain summaries and recovered users, never full
# canonical answers, transcripts, or a second durable conversation representation.
_PROMPT_SNAPSHOTS: OrderedDict[tuple[Path, str, str], _PromptView] = OrderedDict()
_PROMPT_SNAPSHOT_LOCK = threading.Lock()


def _prompt_view_snapshot(
    session_key: str,
    *,
    history: HistoryReader,
    session_turns_loader: Callable[[], list[_SessionBackfillTurn]] | None = None,
    session_version_loader: Callable[[], tuple[str, int] | None] | None = None,
) -> tuple[_PromptView, str | None]:
    path = history.storage_path

    def read_revision() -> str | None:
        version = session_version_loader() if session_version_loader is not None else None
        return prompt_index_revision(session_key, version, history=history)

    revision = read_revision()
    cache_key = (path, session_key, revision) if revision else None
    if cache_key:
        with _PROMPT_SNAPSHOT_LOCK:
            cached = _PROMPT_SNAPSHOTS.get(cache_key)
            if cached is not None and (not cached.needs_canonical or session_version_loader is not None):
                _PROMPT_SNAPSHOTS.move_to_end(cache_key)
                return cached, revision
    view = _build_prompt_view(session_key, history=history, session_turns_loader=session_turns_loader)
    # A caller supplying only messages cannot validate canonical changes, so a
    # recovered view needs a version loader before it can be reused.
    if (view.needs_canonical and session_version_loader is None) or revision != read_revision():
        return view, None
    if cache_key:
        with _PROMPT_SNAPSHOT_LOCK:
            _PROMPT_SNAPSHOTS[cache_key] = view
            _PROMPT_SNAPSHOTS.move_to_end(cache_key)
            while len(_PROMPT_SNAPSHOTS) > 8:
                _PROMPT_SNAPSHOTS.popitem(last=False)
    return view, revision


class PromptIndexResponse(TypedDict):
    prompts: Sequence[PromptSummary]
    replaceFrom: int
    revision: NotRequired[str | None]


def prompt_index_response(
    session_key: str,
    previous_revision: str | None,
    *,
    history: HistoryReader,
    session_messages_loader: Callable[[], list[dict[str, Any]] | None] | None = None,
    session_version_loader: Callable[[], tuple[str, int] | None] | None = None,
) -> PromptIndexResponse:
    path = history.storage_path
    with _PROMPT_SNAPSHOT_LOCK:
        previous = _PROMPT_SNAPSHOTS.get((path, session_key, previous_revision)) if previous_revision else None
    view, revision = _prompt_view_snapshot(
        session_key,
        history=history,
        session_turns_loader=lambda: _session_backfill_turns(
            session_key, (session_messages_loader() if session_messages_loader else None) or [],
        ),
        session_version_loader=session_version_loader,
    )
    current = view.prompts
    if revision is None:
        return {"prompts": current, "replaceFrom": 0}
    if previous is not None and previous_revision == revision:
        return {"prompts": (), "replaceFrom": len(current), "revision": revision}
    replace_from = 0
    if previous is not None:
        for old, new in zip(previous.prompts, current):
            if old != new:
                break
            replace_from += 1
    return {"prompts": current[replace_from:], "replaceFrom": replace_from, "revision": revision}
