"""Durable per-task subagent transcript storage.

Subagent transcripts are written as per-task JSONL files under
``<workspace>/memory/subagents/<task_id>.jsonl``. They stay inside the agent
workspace so the main agent can read them with the existing filesystem tools,
and they never enter ``memory/history.jsonl`` or any session store, so they
cannot pollute main-agent prompt injection or Dream consolidation.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, cast

from loguru import logger

from nanobot.runtime_context import public_history_messages
from nanobot.session.history_visibility import is_hidden_history_message

#: Keep the newest N transcripts per workspace.
TRANSCRIPT_RETENTION_COUNT = 50
#: Maximum serialized transcript size in bytes. Once reached, records stop
#: appending and a terminal marker record is written, so truncation is never
#: silent.
TRANSCRIPT_MAX_BYTES = 1 * 1024 * 1024

_TRUNCATION_MARKER = "transcript truncated at 1 MiB"

_THINKING_KEYS = frozenset({"reasoning_content", "thinking_blocks"})


class SubagentTranscriptStore:
    """Append-safe per-task JSONL transcript storage under the agent workspace."""

    def __init__(self, workspace: Path) -> None:
        self._root = Path(workspace).expanduser().resolve() / "memory" / "subagents"

    @property
    def root(self) -> Path:
        """The transcript directory (created lazily on first write)."""
        return self._root

    def path_for(self, task_id: str) -> Path:
        """Return the transcript file path for *task_id*."""
        return self._root / f"{task_id}.jsonl"

    def write(
        self,
        task_id: str,
        messages: Iterable[Mapping[str, Any]],
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        """Normalize, stamp, cap, and atomically write a transcript.

        Returns the written file path. The write is atomic (temp file +
        fsync + ``os.replace``), so a crash or concurrent reader never
        observes a torn file. Records beyond the size cap are dropped and a
        terminal marker record is appended; a line is never truncated
        mid-record.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(task_id)
        records: list[dict[str, Any]] = []
        for message in public_history_messages(messages):
            if is_hidden_history_message(message):
                continue
            record = {
                key: value
                for key, value in message.items()
                if key not in _THINKING_KEYS
            }
            record.setdefault("timestamp", datetime.now().isoformat())
            records.append(record)

        lines = self._serialize(task_id, records)
        if metadata:
            lines.append(
                json.dumps({"_transcript_meta": dict(metadata)}, ensure_ascii=False)
            )
        self._write_atomic(target, lines)
        self._prune()
        return target

    def read(self, task_id: str) -> list[dict[str, Any]]:
        """Return parsed records for *task_id* (``[]`` if absent)."""
        try:
            with self.path_for(task_id).open(encoding="utf-8") as handle:
                return [
                    cast(dict[str, Any], json.loads(line))
                    for line in handle
                    if line.strip()
                ]
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return []

    def list(self) -> list[str]:
        """Return task ids present in the store (directory scan)."""
        if not self._root.is_dir():
            return []
        return sorted(path.stem for path in self._root.glob("*.jsonl"))

    def _serialize(self, task_id: str, records: list[dict[str, Any]]) -> list[str]:
        """Enforce the size cap, appending a terminal marker when truncated."""
        lines: list[str] = []
        total = 0
        truncated = False
        for record in records:
            line = json.dumps(record, ensure_ascii=False)
            if total and total + len(line) + 1 > TRANSCRIPT_MAX_BYTES:
                truncated = True
                break
            total += len(line) + 1
            lines.append(line)
        if truncated:
            marker = json.dumps({"role": "system", "content": _TRUNCATION_MARKER})
            lines.append(marker)
            logger.warning(
                "Subagent transcript for {} exceeded {} bytes; truncating with marker",
                task_id,
                TRANSCRIPT_MAX_BYTES,
            )
        return lines

    def _prune(self) -> None:
        """Keep only the newest N transcript files, sorted by mtime."""
        if not self._root.is_dir():
            return
        files = sorted(self._root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if len(files) <= TRANSCRIPT_RETENTION_COUNT:
            return
        for path in files[: len(files) - TRANSCRIPT_RETENTION_COUNT]:
            try:
                path.unlink()
            except OSError:
                logger.warning("Failed to prune subagent transcript {}", path)

    @staticmethod
    def _write_atomic(target: Path, lines: list[str]) -> None:
        tmp_path = target.with_suffix(target.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
