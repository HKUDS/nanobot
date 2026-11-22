from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from bisect import bisect_left
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, NotRequired, Sequence, TypedDict, cast
from urllib.parse import unquote, urlparse

from loguru import logger

from nanobot.bus.events import INBOUND_META_LOCAL_MEDIA, INBOUND_META_TURN_ID
from nanobot.command.builtin import USER_SHELL_COMMAND
from nanobot.runtime_context import public_history_message
from nanobot.session.automation_turns import is_automation_kind
from nanobot.session.display_history import (
    HISTORY_GENERATION_METADATA_KEY,
    HistoryFact,
    HistoryReader,
)
from nanobot.session.history_graph import (
    decode_graph,
    decode_snapshot,
    graph_decoding,
)
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import Session, SessionManager
from nanobot.session.message_content import message_text
from nanobot.session.session_messages import (
    session_message_envelope,
    session_message_public_metadata,
)
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.session.state import SessionOperationQueueFullError
from nanobot.webui.history import (
    fact_from_record,
    initialize_history,
    record_from_fact,
    turn_record_page,
)
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY
from nanobot.webui.outbound_wire import project_tool_events
from nanobot.webui.session_identity import webui_session_key
from nanobot.webui.transcript_replay import (
    WEBUI_REPLAY_IDENTITY_KEY,
    compact_completed_stream_deltas,
    encode_page_cursor,
    ensure_replay_identities,
    parse_replay_identity,
    projection_event_id,
    read_trace_turn,
    select_transcript_page,
    split_transcript_turns,
)
from nanobot.webui.transcript_replay import (
    TranscriptReplayStats as TranscriptReplayStats,
)
from nanobot.webui.transcript_replay import (
    compact_legacy_records as compact_legacy_records,
)
from nanobot.webui.transcript_replay import (
    decode_transcript_cursor as decode_transcript_cursor,
)
from nanobot.webui.transcript_trace import (
    TraceProjection,
    index_trace_projection,
    parse_trace_detail_ref,
)
from nanobot.webui.transcript_trace import (
    tool_trace_lines_from_events as tool_trace_lines_from_events,
)

WEBUI_TRANSCRIPT_SCHEMA_VERSION = 3
WEBUI_FORK_MARKER_EVENT = "fork_marker"
WEBUI_TRANSCRIPT_INCOMPLETE_KEY = "transcript_incomplete"
_DEFAULT_TRANSCRIPT_PAGE_LIMIT = 160
_MAX_TRANSCRIPT_PAGE_LIMIT = 1000
_MAX_TRANSCRIPT_PAGE_RECORDS = 4_000
_MAX_TRANSCRIPT_PAGE_BYTES = 20 * 1024 * 1024
_MAX_INLINE_TRACE_DETAIL_BYTES = 32 * 1024
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
_TURN_DISPLAY_EVENTS: frozenset[str] = frozenset({
    "reasoning_delta",
    "reasoning_end",
    "delta",
    "stream_end",
    "message",
    "file_edit",
    "model_request",
    "turn_end",
})
MAX_SESSION_MENTIONS = 8
_SESSION_MENTION_NAME_RE = re.compile(r"^[\w-]+$")
_SESSION_HANDLE_ID_RE = re.compile(r"^handle_[0-9a-f]{32}$")


def _response_sources(value: object) -> list[dict[str, str | bool]]:
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


class _SessionBackfillTurn(NamedTuple):
    user_event: dict[str, Any]
    assistant_signature: tuple[str, ...]
    assistant_records: tuple[dict[str, Any], ...]


def _coerce_page_limit(limit: int | None) -> int:
    if limit is None:
        return _DEFAULT_TRANSCRIPT_PAGE_LIMIT
    return max(1, min(_MAX_TRANSCRIPT_PAGE_LIMIT, int(limit)))


def read_transcript_lines(session_key: str, *, history: HistoryReader) -> list[dict[str, Any]]:
    return [record_from_fact(fact, session_key) for fact in history.all_facts()]


def find_fork_input(history: HistoryReader, input_id: str) -> tuple[int, int, HistoryFact] | None:
    if entry := next(history.inputs_by_id(input_id), None):
        return entry
    # Before durable input IDs, replay identified a user by turn or its position in the transcript.
    match = None
    for ordinal, position, fact in history.inputs_by_id(None):
        legacy_id = f"user:{fact.turn_id}" if fact.turn_id else projection_event_id({
            WEBUI_REPLAY_IDENTITY_KEY: f"turn:{ordinal}:record:{position}",
        })
        if input_id == legacy_id:
            if match is not None:
                return None
            match = (ordinal, position, fact)
    return match


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
        if event.get("event") == "user" and (turn_id := (metadata or {}).get(WEBUI_TURN_METADATA_KEY)):
            event["input_id"] = f"user:{turn_id}"
        if include_source and metadata is not None and "response_input_ids" in metadata:
            event["response_input_ids"] = list(metadata["response_input_ids"])
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
        envelope = session_message_envelope(metadata)
        if envelope is not None and envelope["target_session_key"] != webui_session_key(chat_id):
            envelope = None
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
        if envelope is not None:
            event.update(
                created_at_ms=envelope["created_at_ms"],
                session_message=session_message_public_metadata(envelope),
                input_id=f"session-message:{envelope['message_id']}",
            )
        return await self.prepare_and_append(chat_id, event, metadata=metadata, phase="user")

    async def append(
        self, chat_id: str, event: dict[str, Any], *, metadata: dict[str, Any] | None,
    ) -> bool:
        return await self.append_many(chat_id, [event], metadata=metadata)

    async def append_many(
        self, chat_id: str, events: Sequence[dict[str, Any]], *, metadata: dict[str, Any] | None,
        raise_storage_errors: bool = False,
    ) -> bool:
        if self.sessions is None:
            return True  # A transport-only channel has no durable session service.
        generation = (metadata or {}).get(HISTORY_GENERATION_METADATA_KEY)
        if not isinstance(generation, str) or not generation:
            self._log.warning("history event has no admitted generation for {}", chat_id)
            return False
        facts: list[HistoryFact] = []
        valid = True
        for event in events:
            try:
                fact = fact_from_record(_record_for_append(event))
                facts.append(fact)
            except (ValueError, TypeError) as exc:
                self._log.warning("history append failed for {}: {}", chat_id, exc)
                valid = False
        if not facts:
            return False
        try:
            errors = await self.sessions.state.append_history(webui_session_key(chat_id), facts,
                                                              expected_generation=generation,
                                                              skip_invalid=len(events) > 1)
            for error in errors:
                self._log.warning("history append failed for {}: {}", chat_id, error)
            valid = valid and not errors
        except (OSError, ValueError, TypeError, sqlite3.Error, SessionConflictError, SessionOperationQueueFullError) as exc:
            if raise_storage_errors and isinstance(exc, (OSError, sqlite3.OperationalError, SessionOperationQueueFullError)):
                raise
            self._log.warning("history append failed for {}: {}", chat_id, exc)
            return False
        return valid

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


def _is_user_shell_command(message: Mapping[str, Any]) -> bool:
    content = message.get("content")
    return (
        message.get("role") == "user" and message.get("_command") is True
        and isinstance(content, str)
        and (content == USER_SHELL_COMMAND or content.startswith(f"{USER_SHELL_COMMAND} "))
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
    text = message_text(message.get("content"))
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
    if isinstance(message_id := message.get("input_id"), str) and message_id:
        event["input_id"] = message_id
    input_id = message.get(INBOUND_META_TURN_ID)
    if isinstance(input_id, str) and _WEBUI_TURN_ID_RE.fullmatch(input_id):
        event["turn_id"] = input_id
        event["turn_phase"] = "user"
        event[WEBUI_REPLAY_IDENTITY_KEY] = f"input:{session_key}:{input_id}"
    elif canonical_position is not None:
        event[WEBUI_REPLAY_IDENTITY_KEY] = f"canonical:{session_key}:message:{canonical_position}"
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
    if "response_input_ids" in message:
        event["response_input_ids"] = message["response_input_ids"]
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
        if current_user is None:
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


def _transcript_turn_signature(records: list[dict[str, Any]]) -> tuple[str, ...]:
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


def _find_recoverable_session_turn(
    session_turns: list[_SessionBackfillTurn],
    user_events: list[dict[str, Any]],
) -> _SessionBackfillTurn | None:
    if len(user_events) != 1:
        return None
    signature = _user_recovery_signature(user_events[0])
    matches = [
        turn
        for turn in session_turns
        if _user_recovery_signature(turn.user_event) == signature
    ]
    return matches[0] if len(matches) == 1 and matches[0].assistant_records else None


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


def _recover_incomplete_fragment(
    lines: list[dict[str, Any]], session_turn: _SessionBackfillTurn, *, terminal: bool,
) -> list[dict[str, Any]]:
    retained = [record for record in lines if not _is_recoverable_answer_record(record)]
    if not terminal:
        return retained
    turn_end = retained.pop()
    stable_end_ms = _valid_created_at_ms(turn_end.get("created_at_ms"))
    turn_id = turn_end.get("turn_id")
    for index, source in enumerate(session_turn.assistant_records):
        answer = dict(source)
        if isinstance(turn_id, str) and turn_id:
            answer["turn_id"] = turn_id
            answer["turn_phase"] = "answer"
        if stable_end_ms is not None:
            answer["created_at_ms"] = max(0, stable_end_ms - len(session_turn.assistant_records) + index)
        retained.append(answer)
    completed_end = dict(turn_end)
    completed_end.pop(WEBUI_TRANSCRIPT_INCOMPLETE_KEY, None)
    retained.append(completed_end)
    return retained


def _recover_incomplete_turns(
    lines: list[dict[str, Any]],
    session_turns: list[_SessionBackfillTurn],
) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    for turn in split_transcript_turns(lines):
        turn_end = turn[-1] if turn else None
        if (
            not isinstance(turn_end, dict)
            or turn_end.get("event") != "turn_end"
            or turn_end.get(WEBUI_TRANSCRIPT_INCOMPLETE_KEY) is not True
        ):
            recovered.extend(turn)
            continue

        user_events = [record for record in turn if record.get("event") == "user"]
        session_turn = _find_recoverable_session_turn(session_turns, user_events)
        if session_turn is None:
            recovered.extend(turn)
            continue

        recovered.extend(_recover_incomplete_fragment(turn, session_turn, terminal=True))
    return recovered


def _needs_user_event_backfill(
    lines: list[dict[str, Any]], history: HistoryReader, *, legacy: bool = True,
) -> bool:
    # A request start identifies response targets, but is not persisted answer evidence.
    display_lines = [record for record in lines if record.get("event") != "model_request"]
    referenced_inputs = {
        input_id
        for record in display_lines
        if isinstance(references := record.get("response_input_ids"), list)
        for input_id in cast(list[object], references)
        if isinstance(input_id, str) and input_id
    }
    return any(not history.has_input(input_id) for input_id in referenced_inputs) or legacy and any(
        not any(record.get("event") == "user" or isinstance(record.get("response_input_ids"), list) for record in turn)
        and _transcript_turn_signature(turn)
        for turn in split_transcript_turns(display_lines)
    )


def _with_backfilled_user(
    records: list[dict[str, Any]],
    user_event: dict[str, Any],
) -> list[dict[str, Any]]:
    input_id = user_event.get("input_id")
    legacy = not any("response_input_ids" in record for record in records)
    for index, rec in enumerate(records):
        if (
            input_id and input_id in rec.get("response_input_ids", [])
            or (not input_id or legacy) and rec.get("event") in _TURN_DISPLAY_EVENTS
        ):
            if input_id:
                references = rec.get("response_input_ids")
                if isinstance(references, list):
                    references = cast(list[object], references)
                    following = {value for value in references[references.index(input_id) + 1:]
                                 if isinstance(value, str)}
                    index = next((i for i, prior in enumerate(records[:index])
                                  if prior.get("event") == "user" and prior.get("input_id") in following), index)
            return [*records[:index], dict(user_event), *records[index:]]
    return records


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
    return False


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
    identity = parse_trace_detail_ref(detail_ref)
    if identity is None:
        return None
    ordinal, message_id = identity
    turn = read_trace_turn(
        ordinal, history=history,
        max_records=_MAX_TRANSCRIPT_PAGE_RECORDS, max_bytes=_MAX_TRANSCRIPT_PAGE_BYTES,
    )
    if turn is None:
        return None
    lines, _ = compact_completed_stream_deltas(turn)
    return _index_trace_projection(lines).detail(message_id)


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
        "projection_id": projection_event_id(record),
        **_client_projection_turn_fields(record),
    }
    created_at_ms = _valid_created_at_ms(record.get("created_at_ms"))
    if created_at_ms is not None:
        fields["created_at_ms"] = created_at_ms
    if isinstance(input_id := record.get("input_id"), str):
        fields["input_id"] = input_id
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


def _augment_projected_message(
    record: dict[str, Any], projected: dict[str, Any], *,
    augment_media: Callable[[list[str]], list[dict[str, Any]]] | None,
    augment_text: Callable[[str], str] | None,
    cached: bool = False,
) -> None:
    if augment_text is not None and projected.get("render_as") != "text":
        projected["text"] = augment_text(projected["text"])
    if augment_media is not None and isinstance(raw_media := record.get("media"), list):
        paths = [path for path in cast(list[object], raw_media) if isinstance(path, str) and path]
        if paths:
            # When re-signing local paths, do not fall back to stale signed URLs.
            media = augment_media(paths)
            if media:
                projected["media_urls"] = media
            else:
                projected.pop("media_urls", None)
            return
    if not cached and (media := _media_from_signed_urls(record.get("media_urls"))):
        projected["media_urls"] = media


def _client_projection_event(
    record: dict[str, Any],
    *,
    augment_user_media: Callable[[list[str], list[str]], list[dict[str, Any]]] | None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None,
    augment_assistant_text: Callable[[str], str] | None,
) -> dict[str, Any] | None:
    event = record.get("event")
    common = _client_projection_common_fields(record)
    if event in {"delta", "stream_end", "message"}:
        if "response_sources" in record:
            common["response_sources"] = _response_sources(record["response_sources"])
        if "response_input_ids" in record:
            common["response_input_ids"] = record["response_input_ids"]
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
        if record.get("text_from_seq") is not None:
            projected["text_from_seq"] = record["text_from_seq"]
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
        render_as_text = record.get("render_as") == "text"
        projected = {"event": "message", **common, "text": content}
        if record.get("side_channel") is True:
            projected["side_channel"] = True
        if render_as_text:
            projected["render_as"] = "text"
        kind = record.get("kind")
        if kind in {"tool_hint", "progress", "reasoning"}:
            projected["kind"] = kind
        tool_events = _normalize_tool_events(record.get("tool_events"))
        if tool_events:
            projected["tool_events"] = tool_events
        _augment_projected_message(
            record, projected, augment_media=augment_assistant_media, augment_text=augment_assistant_text,
        )
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
        if (graph := decode_graph(record.get("context_graph"))) is not None:
            projected["context_graph"] = graph
        if (snapshot := decode_snapshot(record.get("context_snapshot"))) is not None:
            projected["context_snapshot"] = snapshot
        reason = record.get("reason")
        if isinstance(reason, str) and reason in {"idle", "context_pressure", "manual", "provider_native"}:
            projected["reason"] = reason
        return projected

    if event in {"turn_end", "model_request"}:
        projected = {"event": event, **common}
        if event == "model_request":
            request_id, run_id = record.get("request_id"), record.get("run_id")
            sequence, phase = record.get("sequence"), record.get("phase")
            if (
                not isinstance(request_id, str) or not request_id
                or not isinstance(run_id, str) or not run_id
                or not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1
                or phase not in ("started", "completed", "failed", "cancelled")
            ):
                return None
            projected.update(request_id=request_id, run_id=run_id, sequence=sequence, phase=phase)
            if phase == "started" and isinstance(references := record.get("response_input_ids"), list):
                input_ids = [value for value in cast(list[object], references) if isinstance(value, str) and value]
                if input_ids:
                    projected["response_input_ids"] = input_ids
            if "request_usage" in record:
                projected["request_usage"] = _sanitize_turn_usage(record["request_usage"]) or None
            if (graph := decode_graph(record.get("context_graph"))) is not None:
                projected["context_graph"] = graph
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
            if round_usages or event == "model_request":
                projected["round_usages"] = round_usages[-8:] if event == "model_request" else round_usages
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


def _project_trace_event(record: dict[str, Any]) -> dict[str, Any] | None:
    return _client_projection_event(
        record, augment_user_media=None, augment_assistant_media=None, augment_assistant_text=None,
    )


def _index_trace_projection(lines: list[dict[str, Any]]) -> TraceProjection:
    return index_trace_projection(lines, _project_trace_event, max_inline_bytes=_MAX_INLINE_TRACE_DETAIL_BYTES)


def _client_projection_events(
    lines: list[dict[str, Any]],
    *,
    augment_user_media: Callable[[list[str], list[str]], list[dict[str, Any]]] | None,
    augment_assistant_media: Callable[[list[str]], list[dict[str, Any]]] | None,
    augment_assistant_text: Callable[[str], str] | None,
    defer_traces: bool = True,
) -> tuple[list[dict[str, Any]], int | None]:
    events: list[dict[str, Any]] = []
    fork_boundary_event_index: int | None = None
    traces = _index_trace_projection(lines) if defer_traces else None
    deferred_until = 0
    for index, record in enumerate(lines):
        if index < deferred_until and record.get("event") != "model_request":
            continue
        if record.get("event") == WEBUI_FORK_MARKER_EVENT:
            if fork_boundary_event_index is None:
                fork_boundary_event_index = len(events)
            continue
        cached = traces.events.get(index) if traces is not None else None
        if cached is not None:
            event = cached
            _augment_projected_message(
                record, event, augment_media=augment_assistant_media,
                augment_text=augment_assistant_text, cached=True,
            )
        else:
            event = _client_projection_event(
                record,
                augment_user_media=augment_user_media,
                augment_assistant_media=augment_assistant_media,
                augment_assistant_text=augment_assistant_text,
            )
        if event is None:
            continue
        if traces is not None and (group := traces.groups.get(index)) is not None:
            traces.summarize(lines, group, event)
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
                WEBUI_REPLAY_IDENTITY_KEY: f"session:{session.key}:{index}:{offset}",
            })
            rows.append(record)
    if not active and rows:
        rows.append({"event": "turn_end", "chat_id": chat_id,
                     "turn_id": turn_id, "latency_ms": latency_ms,
                     WEBUI_REPLAY_IDENTITY_KEY: f"session:{session.key}:end"})
    events = [event for record in rows if (event := _client_projection_event(
        record, augment_user_media=augment_user_media, augment_assistant_media=augment_assistant_media,
        augment_assistant_text=augment_assistant_text,
    )) is not None]
    return {"schemaVersion": WEBUI_TRANSCRIPT_SCHEMA_VERSION, "sessionKey": session.key,
            "projection": "events", "events": events,
            "active_turn_id": turn_id if active else None}


@graph_decoding()
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
    include_model_requests: bool = False,
) -> dict[str, Any] | None:
    """Return canonical events, hiding additive request events from old clients."""
    replay_stats = stats or TranscriptReplayStats()
    lines, page = select_transcript_page(
        history=history,
        page_limit=_coerce_page_limit(limit),
        max_records=_MAX_TRANSCRIPT_PAGE_RECORDS,
        max_bytes=_MAX_TRANSCRIPT_PAGE_BYTES,
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

    record_range = page.get("record_range")
    fragment = record_range is not None
    ref = next(history.turns(after=record_range["turn"], before=record_range["turn"] + 1), None) if record_range else None
    needs_backfill = (
        history.has_missing_input_references(ref.ordinal)
        or (ref.user_count == 0 and record_range["start"] == 0 and history.has_navigation_answer(ref.ordinal))
    ) if ref is not None and record_range is not None else _needs_user_event_backfill(lines, history, legacy=not fragment)
    backfill_plan: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    if needs_backfill:
        view, _ = _prompt_view_snapshot(
            session_key, history=history, session_turns_loader=load_session_turns,
            session_version_loader=session_version_loader,
        )
        backfill_plan = view.backfill_plan
        recovered_lines: list[dict[str, Any]] = []
        for turn in split_transcript_turns(lines):
            first_identity = parse_replay_identity(turn[0].get(WEBUI_REPLAY_IDENTITY_KEY))
            if first_identity is None:
                recovered_lines.extend(turn)
                continue
            ordinal = first_identity[0]
            for anchor, user in backfill_plan.get(ordinal, []):
                if record_range is not None and not record_range["start"] <= anchor < record_range["end"]:
                    continue
                index = next((i for i, record in enumerate(turn)
                              if (parsed := parse_replay_identity(record.get(WEBUI_REPLAY_IDENTITY_KEY))) is not None
                              and parsed[0] == ordinal
                              and parsed[1] >= anchor), len(turn))
                turn.insert(index, dict(user))
            recovered_lines.extend(turn)
        lines = recovered_lines
    if record_range is not None:
        if ref is not None and ref.user_count == 1:
            ordinal = ref.ordinal
            terminal = record_range["end"] == ref.record_count
            if terminal:
                incomplete = bool(lines and lines[-1].get("event") == "turn_end"
                                  and lines[-1].get(WEBUI_TRANSCRIPT_INCOMPLETE_KEY) is True)
            else:
                incomplete = history.incomplete_completion_marker(ordinal, ref.record_count - 1)
            if incomplete and (position := history.unique_user_position(ordinal)) is not None:
                identity = f"turn:{ordinal}:record:{position}"
                user = next((record for record in lines if record.get(WEBUI_REPLAY_IDENTITY_KEY) == identity), None)
                if user is None:
                    records, _, _, _ = turn_record_page(
                        history, ordinal, start=position, end=position + 1, reverse=False,
                        max_records=1, max_bytes=_MAX_TRANSCRIPT_PAGE_BYTES, allow_oversized=True,
                    )
                    if records:
                        user = records[0]
                if user is not None:
                    users = [user, *(item for _, item in backfill_plan.get(ordinal, []))]
                    session_turn = _find_recoverable_session_turn(load_session_turns(), users)
                    if session_turn is not None:
                        lines = _recover_incomplete_fragment(lines, session_turn, terminal=terminal)
                        if terminal:
                            page["recovered_answers"] = True
    elif _needs_incomplete_turn_recovery(lines):
        lines = _recover_incomplete_turns(lines, load_session_turns())
    bang_inputs = {
        record.get("turn_id") for record in lines
        if record.get("event") == "user" and isinstance(text := record.get("text"), str)
        and text.startswith("!")
    }
    legacy_shell_candidates = {
        record.get("turn_id") for record in lines
        if record.get("event") == "message" and record.get("kind") is None
        and record.get("render_as") != "text" and record.get("turn_id") in bang_inputs
        and isinstance(record.get("turn_id"), str)
    }
    if legacy_shell_candidates and not fragment:
        if session_messages is None and session_messages_loader is not None:
            session_messages = session_messages_loader()
        shell_turns = {
            message.get(INBOUND_META_TURN_ID) for message in session_messages or []
            if _is_user_shell_command(message)
            and message.get(INBOUND_META_TURN_ID) in legacy_shell_candidates
        }
        lines = [
            {**record, "render_as": "text"}
            if record.get("event") == "message" and record.get("kind") is None
            and record.get("turn_id") in shell_turns else record
            for record in lines
        ]
    lines = ensure_replay_identities(lines)
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
        defer_traces=not fragment,
    )
    if not include_model_requests:
        # Select pages and stable identities before filtering request telemetry.
        if fork_boundary_event_index is not None:
            fork_boundary_event_index = sum(
                event["event"] != "model_request" for event in events[:fork_boundary_event_index]
            )
        events = [event for event in events if event["event"] != "model_request"]
    replay_stats.replay_ms += int((time.perf_counter() - replay_started) * 1000)
    payload["projection"] = "events"
    payload["events"] = events
    page["loaded_event_count"] = len(events)
    if fork_boundary_event_index is not None:
        payload["fork_boundary_event_index"] = fork_boundary_event_index
    payload["page"] = page
    return payload


class PromptSummary(TypedDict):
    inputId: str
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
    input_ids: tuple[str, ...] | None


class _ChunkPromptView(NamedTuple):
    prompts: tuple[PromptSummary, ...]
    candidates: tuple[_BackfillCandidate, ...]
    input_ids: frozenset[str]
    answers: dict[str, str]
    turns: dict[int, list[dict[str, Any]]]


class _PromptView(NamedTuple):
    prompts: tuple[PromptSummary, ...]
    backfill_plan: dict[int, list[tuple[int, dict[str, Any]]]]
    needs_canonical: bool


def _assistant_signature_identity(signature: tuple[str, ...]) -> str:
    if not signature:
        return ""
    return hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode("utf-8")).hexdigest()


def prompt_index_revision(session_key: str, session_version: tuple[str, int] | None = None, *, history: HistoryReader) -> str | None:
    """Validate display inputs without reading canonical history or constructing a view."""
    return webui_transcript_revision(session_key, history=history, variant={"session_version": session_version})


def _prompt_summary(
    record: dict[str, Any], ordinal: int, answer: str, position: int = 0,
) -> PromptSummary:
    return {
        "id": projection_event_id(record),
        "inputId": str(record.get("input_id") or ""),
        "preview": str(record.get("text") or "").strip()[:320],
        "answerPreview": answer,
        "createdAt": _valid_created_at_ms(record.get("created_at_ms")) or 0,
        "cursor": encode_page_cursor(ordinal, position),
        "turnId": str(record.get("turn_id") or ""),
    }


def _history_prompt_summaries(history: HistoryReader) -> _ChunkPromptView:
    result: list[PromptSummary] = []
    candidates: list[_BackfillCandidate] = []
    input_ids: set[str] = set()
    answers: dict[str, str] = {}
    response_inputs: dict[int, list[str]] = {}
    turns: dict[int, list[dict[str, Any]]] = {}
    for ordinal, position, fact in history.navigation():
        record = record_from_fact(fact, history.key)
        record[WEBUI_REPLAY_IDENTITY_KEY] = f"turn:{ordinal}:record:{position}"
        turns.setdefault(ordinal, []).append(record)
        if record.get("event") in {"message", "stream_end"} and not record.get("kind"):
            if isinstance(references := record.get("response_input_ids"), list):
                identifiers = [value for value in cast(list[object], references) if isinstance(value, str) and value]
                response_inputs.setdefault(ordinal, []).extend(identifiers)
                answer = str(record.get("text") or "").strip()[:240]
                if answer:
                    for input_id in identifiers:
                        answers.setdefault(input_id, answer)
    for ordinal, records in turns.items():
        has_user = any(record.get("event") == "user" for record in records)
        signature = _transcript_turn_signature(records)
        candidates.append(_BackfillCandidate(
            ordinal, _assistant_signature_identity(signature),
            signature[0][:240] if signature else "", has_user,
            tuple(dict.fromkeys(response_inputs[ordinal])) if ordinal in response_inputs else None,
        ))
        seen_messages: set[str] = set()
        for index, record in enumerate(records):
            if record.get("event") != "user":
                continue
            position = int(record[WEBUI_REPLAY_IDENTITY_KEY].rsplit(":", 1)[1])
            input_id = record.get("input_id")
            if isinstance(input_id, str) and input_id:
                input_ids.add(input_id)
                result.append(_prompt_summary(record, ordinal, answers.get(input_id, ""), position))
                continue
            provenance = normalize_session_message_ui_metadata(record.get("session_message"))
            if provenance:
                message_id = str(provenance["message_id"])
                if message_id in seen_messages:
                    continue
                seen_messages.add(message_id)
            answer = ""
            for following in records[index + 1:]:
                if following.get("event") == "user":
                    break
                if following.get("event") in {"message", "stream_end"} and not following.get("kind"):
                    answer = str(following.get("text") or "").strip()[:240]
                    if answer:
                        break
            result.append(_prompt_summary(record, ordinal, answer, position))
    return _ChunkPromptView(tuple(result), tuple(candidates), frozenset(input_ids), answers, turns)


def _build_prompt_view(
    *,
    history: HistoryReader,
    session_turns_loader: Callable[[], list[_SessionBackfillTurn]] | None = None,
) -> _PromptView:
    chunk = _history_prompt_summaries(history)
    raw_prompts = list(chunk.prompts)
    candidates = list(chunk.candidates)
    session_turns = None
    needs_canonical = any(
        not set(candidate.input_ids).issubset(chunk.input_ids)
        if candidate.input_ids is not None else not candidate.has_user and bool(candidate.signature)
        for candidate in candidates
    )
    if needs_canonical and session_turns_loader is not None:
        session_turns = session_turns_loader()
    entries: list[tuple[int, PromptSummary, dict[str, Any] | None]] = [
        (cursor.turn if (cursor := decode_transcript_cursor(prompt["cursor"])) else 0, prompt, None)
        for prompt in raw_prompts
    ]
    session_cursor = 0
    signature_positions: dict[str, list[int]] = {}
    for position, turn in enumerate(session_turns or []):
        signature_positions.setdefault(_assistant_signature_identity(turn.assistant_signature), []).append(position)
    canonical_inputs = {
        user["input_id"]: user
        for turn in session_turns or []
        for user in (turn.user_event,)
        if isinstance(user.get("input_id"), str)
    }
    represented = set(chunk.input_ids)
    # Identity references take precedence over legacy answer matching, even when
    # the matching legacy answer occurs earlier in the display history.
    reserved = {input_id for candidate in candidates for input_id in candidate.input_ids or ()
                if input_id in canonical_inputs}
    used_positions: set[int] = set()
    for candidate in candidates:
        if not session_turns:
            break
        if candidate.input_ids is not None:
            for input_id in candidate.input_ids:
                if input_id in represented or input_id not in canonical_inputs:
                    continue
                user = dict(canonical_inputs[input_id])
                summary = _prompt_summary(user, candidate.ordinal, chunk.answers.get(input_id, ""))
                entries.append((candidate.ordinal, summary, user))
                represented.add(input_id)
            continue
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
        if match in used_positions or user.get("input_id") in represented or user.get("input_id") in reserved:
            continue
        used_positions.add(match)
        if isinstance(input_id := user.get("input_id"), str) and input_id:
            represented.add(input_id)
        summary = _prompt_summary(user, candidate.ordinal, candidate.answer_preview)
        entries.append((candidate.ordinal, summary, user))
    backfilled_users: dict[int, list[dict[str, Any]]] = {}
    for ordinal, _, user in entries:
        if user is not None:
            backfilled_users.setdefault(ordinal, []).append(user)
    order: dict[tuple[int, str], int] = {}
    plan: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for ordinal, records in chunk.turns.items():
        users = backfilled_users.get(ordinal, [])
        recovered_ids = {projection_event_id(user) for user in users}
        for user in users:
            records = _with_backfilled_user(records, user)
        next_anchor = 2**63 - 1
        reverse_plan: list[tuple[int, dict[str, Any]]] = []
        for position in range(len(records) - 1, -1, -1):
            record = records[position]
            identity = record.get(WEBUI_REPLAY_IDENTITY_KEY, "")
            if identity.startswith(f"turn:{ordinal}:record:"):
                next_anchor = int(identity.rsplit(":", 1)[1])
            if record.get("event") == "user":
                event_id = projection_event_id(record)
                order[(ordinal, event_id)] = position
                if event_id in recovered_ids:
                    anchor = next_anchor if any("response_input_ids" in item for item in records) else 0
                    reverse_plan.append((anchor, record))
        if reverse_plan:
            plan[ordinal] = list(reversed(reverse_plan))
    for ordinal, prompt, user in entries:
        if user is not None:
            anchor = next(anchor for anchor, record in plan[ordinal]
                          if projection_event_id(record) == prompt["id"])
            prompt["cursor"] = encode_page_cursor(ordinal, anchor)
    entries.sort(key=lambda entry: (entry[0], order.get((entry[0], entry[1]["id"]), 0)))
    return _PromptView(tuple(prompt for _, prompt, _ in entries), plan, needs_canonical)


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
    view = _build_prompt_view(history=history, session_turns_loader=session_turns_loader)
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
