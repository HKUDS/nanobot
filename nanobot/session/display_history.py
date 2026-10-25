"""Durable display facts, separate from provider/model messages and transports."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

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
        record = json.dumps({
            "kind": self.kind.value, "content": dict(self.content),
            "turn_id": self.turn_id, "phase": self.phase,
            "sequence": self.sequence, "created_at_ms": self.created_at_ms,
        }, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
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

    def read_entries(
        self, ordinal: int, *, max_records: int | None = None, max_bytes: int | None = None,
    ) -> list[tuple[int, HistoryFact]]:
        clause = "session_key=? AND turn_ordinal=?"
        params = (self.key, ordinal)
        selected: list[int] | None = None
        if max_records is not None and max_bytes is not None:
            # Inspect sizes/positions, not unbounded JSON bodies, before decoding
            # a pathological single turn. Preserve the first input and useful tail.
            priorities: list[tuple[int, int]] = []
            for kinds, order in (((HistoryKind.INPUT,), "ASC"),
                                 ((HistoryKind.COMPLETION,), "DESC"),
                                 ((HistoryKind.ANSWER, HistoryKind.ANSWER_SEGMENT, HistoryKind.ANSWER_FRAGMENT), "DESC")):
                row = self._db.execute(
                    f"SELECT position, length(CAST(record AS BLOB)) FROM history_entries WHERE {clause} "
                    f"AND kind IN ({','.join('?' for _ in kinds)}) ORDER BY position {order} LIMIT 1",
                    (*params, *kinds),
                ).fetchone()
                if row is not None:
                    priorities.append((row[0], row[1]))
            candidates = self._db.execute(
                f"SELECT position, length(CAST(record AS BLOB)) FROM history_entries WHERE {clause} ORDER BY position DESC LIMIT ?",
                (*params, max_records),
            )
            positions: set[int] = set()
            used = 0
            for position, size in (*priorities, *candidates):
                if position not in positions and len(positions) < max_records and used + size <= max_bytes:
                    positions.add(position)
                    used += size
            selected = sorted(positions)
            if not selected:
                return []
            clause += f" AND position IN ({','.join('?' for _ in selected)})"
        return [(row[0], HistoryFact.decode(row[1])) for row in self._db.execute(
            f"SELECT position, record FROM history_entries WHERE {clause} ORDER BY position",
            (*params, *(selected or [])),
        )]

    def user_count_before(self, ordinal: int) -> int:
        return int(self._db.execute(
            "SELECT coalesce(sum(user_count), 0) FROM history_turns WHERE session_key=? AND ordinal<?",
            (self.key, ordinal),
        ).fetchone()[0])

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
