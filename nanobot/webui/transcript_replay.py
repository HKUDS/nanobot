"""Cursor, source page budgets, and stable replay record identity."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, NamedTuple, NotRequired, TypedDict, cast

from nanobot.session.display_history import HistoryReader
from nanobot.session.history_graph import graph_size_adjustment
from nanobot.webui.history import turn_record_page

WEBUI_REPLAY_IDENTITY_KEY = "_webui_replay_identity"


class _RecordRange(TypedDict):
    turn: int
    start: int
    end: int


class ReplayPage(TypedDict):
    before_cursor: str | None
    has_more_before: bool
    after_cursor: str | None
    has_more_after: bool
    loaded_event_count: int
    user_message_offset: int
    history_generation: NotRequired[str | None]
    truncated_oversized_turn: NotRequired[bool]
    record_range: NotRequired[_RecordRange]
    recovered_answers: NotRequired[bool]


class _TranscriptTurnRef(NamedTuple):
    ordinal: int
    records: list[dict[str, Any]]
    start: int
    end: int
    total: int


class _PageCursor(NamedTuple):
    turn: int
    position: int = 0


def encode_page_cursor(before_turn_ordinal: int, position: int = 0) -> str:
    data = {"before_turn": before_turn_ordinal}
    if position:
        data["position"] = position
    raw = json.dumps(
        data,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_transcript_cursor(value: str | None) -> _PageCursor | None:
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
    position = cursor_data.get("position", 0)
    if (
        isinstance(before_turn, bool) or not isinstance(before_turn, int) or before_turn < 0
        or isinstance(position, bool) or not isinstance(position, int) or position < 0
    ):
        return None
    return _PageCursor(before_turn, position)


@dataclass(slots=True)
class TranscriptReplayStats:
    """Selected-source page diagnostics; canonical recovery reads are separate."""

    effective_limit: int = 0
    source_bytes: int = 0
    parsed_records: int = 0
    _selected_bytes: int = 0
    selected_records: int = 0
    compacted_delta_records: int = 0
    replay_ms: int = 0
    capped_by_bytes: bool = False
    capped_by_records: bool = False
    truncated_oversized_turn: bool = False
    _selected_bytes_loader: Callable[[], int] | None = field(
        default=None, init=False, repr=False, compare=False,
    )

    @property
    def selected_bytes(self) -> int:
        if self._selected_bytes_loader is not None:
            self._selected_bytes = self._selected_bytes_loader()
            self._selected_bytes_loader = None
        return self._selected_bytes

    @selected_bytes.setter
    def selected_bytes(self, value: int) -> None:
        self._selected_bytes = value
        self._selected_bytes_loader = None

    def measure_selected(self, records: list[dict[str, Any]]) -> None:
        self.selected_records = len(records)
        self._selected_bytes = 0
        self._selected_bytes_loader = (lambda: _records_bytes(records)) if records else None


def _record_json_line(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def _records_bytes(records: list[dict[str, Any]]) -> int:
    total = 0
    for record in records:
        total += len(_record_json_line(record).encode("utf-8")) + graph_size_adjustment(record) + 1
    return total


def _stream_key(record: dict[str, Any], stream: str) -> tuple[str, str, str]:
    raw_turn_id = record.get("turn_id")
    turn_id = raw_turn_id if isinstance(raw_turn_id, str) else ""
    raw_phase = record.get("turn_phase")
    phase = raw_phase if isinstance(raw_phase, str) and raw_phase else stream
    raw_stream_id = record.get("stream_id")
    stream_id = raw_stream_id if isinstance(raw_stream_id, str) else ""
    return turn_id, phase, stream_id


def compact_completed_stream_deltas(
    turn: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
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
        # The sealed snapshot is authoritative even when media rewriting changes
        # its text. Only old ends without text need their preceding fragments.
        if not isinstance(completed.get("text"), str):
            completed["text"] = "".join(str(chunk.get("text") or "") for _, chunk in chunks)
        replacements[index] = completed
        dropped_indexes.update(chunk_index for chunk_index, _ in chunks)

    if not dropped_indexes:
        return turn, 0
    return [
        replacements.get(index, record)
        for index, record in enumerate(turn)
        if index not in dropped_indexes
    ], len(dropped_indexes)


def split_transcript_turns(lines: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
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
        if key != WEBUI_REPLAY_IDENTITY_KEY
    }
    raw = json.dumps(
        persisted,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def projection_event_id(record: Mapping[str, Any]) -> str:
    identity = record.get(WEBUI_REPLAY_IDENTITY_KEY)
    if record.get("event") == "user" and isinstance(input_id := record.get("input_id"), str) and input_id:
        identity = f"input:{record.get('chat_id')}:{input_id}"
    if not isinstance(identity, str) or not identity:
        identity = _stable_record_digest(dict(record))
    digest = hashlib.sha256(f"event\0{identity}".encode("utf-8")).hexdigest()[:20]
    return f"history-{digest}"


def ensure_replay_identities(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for fallback_turn_index, turn in enumerate(split_transcript_turns(lines)):
        anchor = next(
            (
                value
                for record in turn
                if isinstance(
                    value := record.get(WEBUI_REPLAY_IDENTITY_KEY),
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
            identity = record.get(WEBUI_REPLAY_IDENTITY_KEY)
            if isinstance(identity, str) and identity:
                annotated.append(record)
                continue
            digest = _stable_record_digest(record)
            occurrence = synthetic_occurrences.get(digest, 0)
            synthetic_occurrences[digest] = occurrence + 1
            annotated.append({
                **record,
                WEBUI_REPLAY_IDENTITY_KEY: (
                    f"{turn_identity}:synthetic:{digest}:{occurrence}"
                ),
            })
    return annotated


def _compact_completed_turns(
    turns: list[list[dict[str, Any]]],
) -> tuple[list[list[dict[str, Any]]], int]:
    compacted: list[list[dict[str, Any]]] = []
    dropped = 0
    for turn in turns:
        next_turn, turn_dropped = compact_completed_stream_deltas(turn)
        compacted.append(next_turn)
        dropped += turn_dropped
    return compacted, dropped


def compact_legacy_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns, _ = _compact_completed_turns(split_transcript_turns(records))
    return [record for turn in turns for record in turn]


_REPLAY_TURN_RECORD_RE = re.compile(r"^turn:(\d+):record:(\d+)$")


def parse_replay_identity(identity: object) -> tuple[int, int] | None:
    if not isinstance(identity, str):
        return None
    match = _REPLAY_TURN_RECORD_RE.fullmatch(identity)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _page_event_count(turn: list[dict[str, Any]]) -> int:
    supported = {
        "user",
        "delta",
        "stream_end",
        "reasoning_delta",
        "reasoning_end",
        "message",
        "file_edit",
        "context_compaction",
        "model_request",
        "turn_end",
    }
    return max(1, sum(record.get("event") in supported for record in turn))


def read_trace_turn(
    ordinal: int, *, history: HistoryReader, max_records: int, max_bytes: int,
) -> list[dict[str, Any]] | None:
    ref = next(history.turns(before=ordinal + 1, after=ordinal), None)
    if ref is None or ref.record_count > max_records or ref.byte_count > max_bytes:
        return None
    records, start, end, _ = turn_record_page(
        history, ordinal, start=0, end=ref.record_count, reverse=False,
        max_records=max_records, max_bytes=max_bytes,
    )
    return records if start == 0 and end == ref.record_count else None


def select_transcript_page(
    *, history: HistoryReader, page_limit: int, max_records: int, max_bytes: int,
    before: str | None, after: str | None, stats: TranscriptReplayStats,
) -> tuple[list[dict[str, Any]], ReplayPage]:
    stats.effective_limit = page_limit
    total_turns = history.turn_count
    before_cursor = decode_transcript_cursor(before)
    after_cursor = decode_transcript_cursor(after)
    forward = after_cursor is not None
    upper = total_turns
    if before_cursor is not None:
        upper = min(before_cursor.turn + int(before_cursor.position > 0), total_turns)
    lower = min(after_cursor.turn, total_turns) if after_cursor is not None else 0
    selected: list[_TranscriptTurnRef] = []
    event_count = record_count = byte_count = 0
    for ref in history.turns(before=upper, after=lower, reverse=not forward):
        start, end = 0, ref.record_count
        if after_cursor is not None and ref.ordinal == after_cursor.turn:
            start = min(after_cursor.position, end)
        if before_cursor is not None and ref.ordinal == before_cursor.turn:
            end = min(before_cursor.position, end)
        if start >= end:
            continue
        requested_partial = start > 0 or end < ref.record_count
        exceeds_records = record_count + end - start > max_records
        exceeds_bytes = byte_count + ref.byte_count > max_bytes
        stats.capped_by_records |= exceeds_records
        stats.capped_by_bytes |= exceeds_bytes
        if selected and (requested_partial or exceeds_records or exceeds_bytes):
            break
        remaining_records = max_records - record_count
        remaining_bytes = max_bytes - byte_count
        turn, first_position, end_position, source_bytes = turn_record_page(
            history, ref.ordinal, start=start, end=end, reverse=not forward,
            max_records=remaining_records, max_bytes=remaining_bytes,
            allow_oversized=not selected,
        )
        stats.parsed_records += len(turn)
        stats.source_bytes += source_bytes
        if source_bytes > remaining_bytes or (len(turn) < end - start and len(turn) < remaining_records):
            stats.capped_by_bytes = True
        if not turn:
            break
        partial = first_position > 0 or end_position < ref.record_count
        # A partial turn is always a page of its own, even when a size estimate
        # from older stored metadata understated the actual encoded bytes.
        if selected and partial:
            break
        raw_count = len(turn)
        if partial:
            stats.truncated_oversized_turn = True
        else:
            turn, dropped = compact_completed_stream_deltas(turn)
            stats.compacted_delta_records += dropped
        selected.append(_TranscriptTurnRef(ref.ordinal, turn, first_position, end_position, ref.record_count))
        record_count += raw_count
        byte_count += source_bytes
        event_count += _page_event_count(turn)
        if partial or event_count >= page_limit:
            break
    chronological = selected if forward else list(reversed(selected))
    # turn_record_page has already annotated each raw source position.
    records = [record for ref in chronological for record in ref.records]
    stats.measure_selected(records)
    if not chronological:
        return [], {"before_cursor": None, "has_more_before": False, "after_cursor": None,
                    "has_more_after": False, "loaded_event_count": 0, "user_message_offset": 0}
    first, last = chronological[0], chronological[-1]
    has_more_before = first.start > 0 or first.ordinal > 0
    has_more_after = last.end < last.total or last.ordinal + 1 < total_turns
    revision = history.revision
    page: ReplayPage = {
        "history_generation": revision[0] if revision is not None else None,
        "before_cursor": encode_page_cursor(first.ordinal, first.start) if has_more_before else None,
        "has_more_before": has_more_before,
        "after_cursor": (
            encode_page_cursor(last.ordinal, last.end) if last.end < last.total
            else encode_page_cursor(last.ordinal + 1) if has_more_after else None
        ),
        "has_more_after": has_more_after, "loaded_event_count": 0,
        "user_message_offset": history.user_count_before(first.ordinal, first.start),
    }
    if first.start > 0 or first.end < first.total:
        page["truncated_oversized_turn"] = True
        page["record_range"] = {"turn": first.ordinal, "start": first.start, "end": first.end}
    return records, page
