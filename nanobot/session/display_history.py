from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from nanobot.session.history_graph import encode_graph_fields, graph_size_adjustment

MAX_HISTORY_FACT_BYTES = 8 * 1024 * 1024
HISTORY_GENERATION_METADATA_KEY = "_history_generation"


class HistoryKind(StrEnum):
    INPUT = "input"
    ANSWER = "answer"
    ANSWER_SEGMENT = "answer_segment"
    REASONING = "reasoning"
    REASONING_SEGMENT = "reasoning_segment"
    PROGRESS = "progress"
    TOOL_ACTIVITY = "tool_activity"
    FILE_ACTIVITY = "file_activity"
    COMPLETION = "completion"
    FORK_BOUNDARY = "fork_boundary"
    COMPACTION = "compaction"
    MODEL_REQUEST = "model_request"
    # Only old transcripts can contain unfinished transport fragments.
    ANSWER_FRAGMENT = "answer_fragment"
    REASONING_FRAGMENT = "reasoning_fragment"


@dataclass(frozen=True)
class HistoryFact:
    kind: HistoryKind
    content: Mapping[str, Any] = field(default_factory=lambda: cast(dict[str, Any], {}))
    turn_id: str | None = None
    phase: str | None = None
    sequence: int | None = None
    created_at_ms: int = 0

    def encode(self) -> str:
        content = encode_graph_fields(self.content)
        payload = {
            "kind": self.kind.value, "content": content,
            "turn_id": self.turn_id, "phase": self.phase,
            "sequence": self.sequence, "created_at_ms": self.created_at_ms,
        }
        record = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        stored_bytes = len(record.encode("utf-8"))
        adjustment = graph_size_adjustment(content)
        logical_bytes = stored_bytes + adjustment
        if max(stored_bytes, logical_bytes) > MAX_HISTORY_FACT_BYTES:
            raise ValueError("history fact exceeds the 8 MiB storage limit")
        if adjustment:
            payload["uncompressed_bytes"] = logical_bytes
            record = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if len(record.encode("utf-8")) > MAX_HISTORY_FACT_BYTES:
                raise ValueError("history fact exceeds the 8 MiB storage limit")
        return record

    @classmethod
    def decode(cls, record: str) -> HistoryFact:
        value = cast(dict[str, Any], json.loads(record))
        return cls(
            HistoryKind(value["kind"]), value["content"], value["turn_id"],
            value["phase"], value["sequence"], value["created_at_ms"],
        )


@dataclass(frozen=True)
class HistoryImport:
    key: str
    facts: list[HistoryFact]
    created_at_ms: int = 0
    updated_at_ms: int = 0


@dataclass(frozen=True)
class HistoryTurn:
    ordinal: int
    record_count: int
    byte_count: int
    user_count: int


@dataclass(frozen=True)
class HistoryEntryPage:
    entries: list[tuple[int, HistoryFact]]
    source_bytes: int


class HistoryReader:
    """A single-session view valid only inside its owner's read transaction."""

    def __init__(self, db: sqlite3.Connection, key: str, storage_path: Path) -> None:
        self._db = db
        self.key = key
        self.storage_path = storage_path

    @property
    def revision(self) -> tuple[str, int] | None:
        row = self._db.execute(
            """SELECT sessions.generation, coalesce(history_heads.revision, -1) FROM sessions
               LEFT JOIN history_heads ON history_heads.session_key=sessions.key WHERE sessions.key=?""",
            (self.key,),
        ).fetchone()
        return (str(row[0]), int(row[1])) if row is not None else None

    @property
    def turn_count(self) -> int:
        return int(self._db.execute(
            "SELECT coalesce(max(ordinal)+1, 0) FROM history_turns WHERE session_key=?",
            (self.key,),
        ).fetchone()[0])

    def turns(
        self, *, before: int | None = None, after: int = 0, reverse: bool = False,
    ) -> Iterator[HistoryTurn]:
        upper = self.turn_count if before is None else before
        order = "DESC" if reverse else "ASC"
        for row in self._db.execute(
            f"""SELECT ordinal, record_count, byte_count, user_count FROM history_turns
                WHERE session_key=? AND ordinal>=? AND ordinal<? ORDER BY ordinal {order}""",
            (self.key, after, upper),
        ):
            yield HistoryTurn(*row)

    def read_entries(self, ordinal: int) -> list[tuple[int, HistoryFact]]:
        return [(row[0], HistoryFact.decode(row[1])) for row in self._db.execute(
            """SELECT position, record FROM history_entries
               WHERE session_key=? AND turn_ordinal=? ORDER BY position""",
            (self.key, ordinal),
        )]

    def read_entry_page(
        self, ordinal: int, *, start: int, end: int, reverse: bool,
        max_records: int, max_bytes: int, allow_oversized: bool = False,
    ) -> HistoryEntryPage:
        """Read a contiguous range, budgeting encoded and expanded source bytes."""
        order = "DESC" if reverse else "ASC"
        sizes = self._db.execute(
            f"""SELECT position, max(length(CAST(record AS BLOB)),
                                    coalesce(json_extract(record, '$.uncompressed_bytes'), 0))
                FROM history_entries WHERE session_key=? AND turn_ordinal=?
                AND position>=? AND position<? ORDER BY position {order} LIMIT ?""",
            (self.key, ordinal, start, end, max_records),
        )
        positions: list[int] = []
        used = 0
        for position, size in sizes:
            # A single persisted fact can exceed a configured page budget. It
            # must still be returned to make progress; storage caps each fact.
            if used + size > max_bytes and (positions or not allow_oversized):
                break
            positions.append(position)
            used += size
            if used >= max_bytes:
                break
        if not positions:
            return HistoryEntryPage([], 0)
        first, last = min(positions), max(positions) + 1
        entries = [(row[0], HistoryFact.decode(row[1])) for row in self._db.execute(
            """SELECT position, record FROM history_entries WHERE session_key=? AND turn_ordinal=?
               AND position>=? AND position<? ORDER BY position""",
            (self.key, ordinal, first, last),
        )]
        return HistoryEntryPage(entries, used)

    def user_count_before(self, ordinal: int, position: int = 0) -> int:
        earlier = int(self._db.execute(
            "SELECT coalesce(sum(user_count), 0) FROM history_turns WHERE session_key=? AND ordinal<?",
            (self.key, ordinal),
        ).fetchone()[0])
        if not position:
            return earlier
        within_turn = self._db.execute(
            """SELECT count(*) FROM history_entries WHERE session_key=? AND turn_ordinal=?
               AND position<? AND kind=?""",
            (self.key, ordinal, position, HistoryKind.INPUT),
        ).fetchone()[0]
        return earlier + int(within_turn)

    def has_input(self, input_id: str) -> bool:
        return self._db.execute(
            """SELECT 1 FROM history_entries WHERE session_key=? AND kind='input'
               AND json_extract(record, '$.content.input_id')=?""",
            (self.key, input_id),
        ).fetchone() is not None

    def has_missing_input_references(self, ordinal: int) -> bool:
        """Detect backfill across page boundaries without loading answer bodies."""
        return self._db.execute(
            """SELECT 1 FROM history_entries AS answer,
                          json_each(answer.record, '$.content.response_input_ids') AS reference
               WHERE answer.session_key=? AND answer.turn_ordinal=? AND answer.kind IN (?, ?, ?)
               AND reference.type='text' AND reference.value!=''
               AND NOT EXISTS (
                   SELECT 1 FROM history_entries AS input WHERE input.session_key=answer.session_key
                   AND input.kind=? AND json_extract(input.record, '$.content.input_id')=reference.value
               ) LIMIT 1""",
            (self.key, ordinal, HistoryKind.ANSWER, HistoryKind.ANSWER_SEGMENT,
             HistoryKind.ANSWER_FRAGMENT, HistoryKind.INPUT),
        ).fetchone() is not None

    def unique_user_position(self, ordinal: int) -> int | None:
        positions = self._db.execute(
            """SELECT position FROM history_entries WHERE session_key=? AND turn_ordinal=?
               AND kind=? ORDER BY position LIMIT 2""",
            (self.key, ordinal, HistoryKind.INPUT),
        ).fetchall()
        return int(positions[0][0]) if len(positions) == 1 else None

    def incomplete_completion_marker(self, ordinal: int, position: int) -> bool:
        """Inspect the terminal marker without decoding the full fact."""
        row = self._db.execute(
            """SELECT json_type(record, '$.content.transcript_incomplete')
               FROM history_entries WHERE session_key=? AND turn_ordinal=? AND position=? AND kind=?""",
            (self.key, ordinal, position, HistoryKind.COMPLETION),
        ).fetchone()
        return bool(row and row[0] == "true")

    def has_navigation_answer(self, ordinal: int) -> bool:
        return self._db.execute(
            """SELECT 1 FROM history_entries WHERE session_key=? AND turn_ordinal=?
               AND kind IN (?, ?, ?) LIMIT 1""",
            (self.key, ordinal, HistoryKind.ANSWER, HistoryKind.ANSWER_SEGMENT, HistoryKind.ANSWER_FRAGMENT),
        ).fetchone() is not None

    def navigation(self) -> Iterator[tuple[int, int, HistoryFact]]:
        """Read input/answer records only, never file diffs or tool result bodies."""
        kinds = (HistoryKind.INPUT, HistoryKind.ANSWER, HistoryKind.ANSWER_SEGMENT,
                 HistoryKind.ANSWER_FRAGMENT, HistoryKind.COMPLETION)
        for row in self._db.execute(
            """SELECT turn_ordinal, position, record FROM history_entries
               WHERE session_key=? AND kind IN (?, ?, ?, ?, ?) ORDER BY turn_ordinal, position""",
            (self.key, *kinds),
        ):
            yield int(row[0]), int(row[1]), HistoryFact.decode(row[2])

    def all_facts(self) -> list[HistoryFact]:
        return [HistoryFact.decode(row[0]) for row in self._db.execute(
            "SELECT record FROM history_entries WHERE session_key=? ORDER BY turn_ordinal, position",
            (self.key,),
        )]
