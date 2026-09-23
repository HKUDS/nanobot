"""Bounded, non-consuming execution output for independent UI readers."""

from __future__ import annotations

from collections import deque
from typing import Literal, TypedDict


class ExecLogChunk(TypedDict):
    seq: int
    stream: Literal["stdout", "stderr"]
    text: str


class ExecLogSnapshot(TypedDict):
    chunks: list[ExecLogChunk]
    cursor: int
    first_seq: int
    omitted_chars: int
    reset: bool


class ExecOutputLog:
    """Keep a tail with monotonic cursors; never touch the model's drain buffer."""

    def __init__(self, max_chars: int = 100_000, max_chunks: int = 512) -> None:
        if max_chars < 1 or max_chunks < 1:
            raise ValueError("output limits must be positive")
        self._max_chars = max_chars
        self._max_chunks = max_chunks
        self._chunks: deque[ExecLogChunk] = deque()
        self._chars = 0
        self._seq = 0
        self._omitted = 0

    def append(self, text: str, stream: Literal["stdout", "stderr"]) -> None:
        if not text:
            return
        self._seq += 1
        if len(text) > self._max_chars:
            self._omitted += len(text) - self._max_chars
            text = text[-self._max_chars:]
        self._chunks.append({"seq": self._seq, "stream": stream, "text": text})
        self._chars += len(text)
        while len(self._chunks) > self._max_chunks or self._chars > self._max_chars:
            old = self._chunks.popleft()
            self._chars -= len(old["text"])
            self._omitted += len(old["text"])

    def read(self, after: int = 0) -> ExecLogSnapshot:
        first = self._chunks[0]["seq"] if self._chunks else self._seq + 1
        reset = after > self._seq or after < first - 1
        cursor = 0 if reset else after
        return {
            "chunks": [chunk.copy() for chunk in self._chunks if chunk["seq"] > cursor],
            "cursor": self._seq, "first_seq": first,
            "omitted_chars": self._omitted, "reset": reset,
        }

    def clear(self) -> None:
        self._chunks.clear()
        self._chars = 0
        self._omitted = 0


class ExecCommandSummary(TypedDict):
    session_id: str
    command: str
    cwd: str
    state: Literal["running", "completed", "failed", "stopped", "timed_out"]
    elapsed_ms: int
    exit_code: int | None


class ExecCommandDetail(ExecCommandSummary, ExecLogSnapshot):
    pass
