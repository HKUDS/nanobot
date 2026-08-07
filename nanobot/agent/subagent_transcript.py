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
from pathlib import Path
from typing import Any, Iterable, Mapping, cast

from loguru import logger

from nanobot.runtime_context import public_history_messages
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.utils.helpers import ensure_dir, timestamp

#: Keep the newest N transcripts per workspace.
TRANSCRIPT_RETENTION_COUNT = 50
#: Maximum serialized transcript size in bytes. Once reached, records stop
#: appending and a terminal marker record is written, so truncation is never
#: silent.
TRANSCRIPT_MAX_BYTES = 1 * 1024 * 1024

_TRUNCATION_MARKER = f"transcript truncated at {TRANSCRIPT_MAX_BYTES // (1024 * 1024)} MiB"

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

    def relative_path_for(self, task_id: str) -> str:
        """Workspace-relative path for *task_id* (for announce metadata)."""
        return f"memory/subagents/{task_id}.jsonl"

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
        ensure_dir(self._root)
        target = self.path_for(task_id)
        now = timestamp()
        records: list[dict[str, Any]] = []
        for message in public_history_messages(messages):
            if is_hidden_history_message(message):
                continue
            record = {
                key: value
                for key, value in message.items()
                if key not in _THINKING_KEYS
            }
            record.setdefault("timestamp", now)
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
        """Return parsed records for *task_id* (``[]`` if absent).

        A single malformed line is skipped rather than losing the whole
        transcript, mirroring ``MemoryStore._read_entries``.
        """
        records: list[dict[str, Any]] = []
        try:
            with self.path_for(task_id).open(encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        parsed = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        logger.warning(
                            "Skipping malformed transcript line for {}", task_id
                        )
                        continue
                    if isinstance(parsed, dict):
                        records.append(cast(dict[str, Any], parsed))
            return records
        except FileNotFoundError:
            return []

    def list(self) -> list[str]:
        """Return task ids present in the store (directory scan)."""
        return sorted(path.stem for path in self._root.glob("*.jsonl"))

    def _serialize(self, task_id: str, records: list[dict[str, Any]]) -> list[str]:
        """Enforce the size cap (measured in UTF-8 bytes), appending a
        terminal marker record when truncated."""
        lines: list[str] = []
        total = 0
        truncated = False
        for record in records:
            line = json.dumps(record, ensure_ascii=False)
            line_bytes = len(line.encode("utf-8"))
            if total and total + line_bytes + 1 > TRANSCRIPT_MAX_BYTES:
                truncated = True
                break
            total += line_bytes + 1
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
        files = list(self._root.glob("*.jsonl"))
        if len(files) <= TRANSCRIPT_RETENTION_COUNT:
            return

        def _mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        files.sort(key=_mtime)
        for path in files[: len(files) - TRANSCRIPT_RETENTION_COUNT]:
            try:
                path.unlink()
            except OSError:
                logger.warning("Failed to prune subagent transcript {}", path)

    @staticmethod
    def _write_atomic(target: Path, lines: list[str]) -> None:
        from contextlib import suppress

        # Refuse to write through a symlinked transcript directory: it lives
        # inside the agent workspace, which the agent itself can mutate, and
        # following a planted symlink would escape the workspace boundary.
        root = target.parent
        if root.is_symlink() or root.parent.is_symlink():
            raise OSError(f"Refusing to write transcripts through a symlinked path: {root}")

        # Create the temp file with O_EXCL|O_NOFOLLOW so a planted symlink at
        # the predictable name can neither be followed nor race the rename.
        tmp_path = target.with_suffix(target.suffix + ".tmp")
        fd: int | None = None
        for attempt in range(3):
            try:
                fd = os.open(
                    tmp_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                break
            except FileExistsError:
                if attempt == 2:
                    raise
                tmp_path = target.with_suffix(f"{target.suffix}.tmp{attempt}")
        if fd is None:  # pragma: no cover - loop above always breaks or raises
            raise OSError(f"Could not reserve temp file for {target}")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)

            # fsync the directory so the rename is durable (mirrors
            # MemoryStore._write_entries). On Windows this raises
            # PermissionError, which is expected and suppressed.
            with suppress(PermissionError):
                dir_fd = os.open(str(target.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
