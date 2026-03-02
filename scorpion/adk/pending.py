"""Message heap for non-blocking generation results.

Tracks background generation workers (video, image, music, speech) and provides
context injection so the agent sees completed/failed results on the next turn.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationResult:
    """A single background generation task."""

    id: str
    session_key: str
    kind: str  # "video", "image", "music", "speech"
    prompt: str
    status: str = "running"  # running | completed | failed
    file_paths: list[str] = field(default_factory=list)
    error: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    _task: asyncio.Task | None = field(default=None, repr=False)


class PendingResults:
    """Session-scoped heap of background generation results.

    Thread-safe via asyncio (single event loop). No locks needed.
    """

    def __init__(self) -> None:
        self._results: dict[str, GenerationResult] = {}  # result_id -> result
        self._by_session: dict[str, list[str]] = {}  # session_key -> [result_id, ...]

    def add(
        self,
        session_key: str,
        kind: str,
        prompt: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Register a new running generation. Returns the result ID."""
        result_id = str(uuid.uuid4())[:8]
        result = GenerationResult(
            id=result_id,
            session_key=session_key,
            kind=kind,
            prompt=prompt,
            params=params or {},
        )
        self._results[result_id] = result
        self._by_session.setdefault(session_key, []).append(result_id)
        return result_id

    def complete(self, result_id: str, file_paths: list[str]) -> None:
        """Mark a generation as completed with output file paths."""
        if result := self._results.get(result_id):
            result.status = "completed"
            result.file_paths = file_paths
            result.finished_at = time.time()

    def fail(self, result_id: str, error: str) -> None:
        """Mark a generation as failed."""
        if result := self._results.get(result_id):
            result.status = "failed"
            result.error = error
            result.finished_at = time.time()

    def register_task(self, result_id: str, task: asyncio.Task) -> None:
        """Associate an asyncio task for cancellation support."""
        if result := self._results.get(result_id):
            result._task = task

    def drain(self, session_key: str) -> list[GenerationResult]:
        """Pop completed/failed results for a session (shown once). Running ones stay."""
        ids = self._by_session.get(session_key, [])
        drained: list[GenerationResult] = []
        remaining: list[str] = []
        for rid in ids:
            result = self._results.get(rid)
            if result is None:
                continue
            if result.status in ("completed", "failed"):
                drained.append(result)
                del self._results[rid]
            else:
                remaining.append(rid)
        self._by_session[session_key] = remaining
        if not remaining:
            self._by_session.pop(session_key, None)
        return drained

    def get_running(self, session_key: str) -> list[GenerationResult]:
        """List in-progress generations for a session."""
        return [
            self._results[rid]
            for rid in self._by_session.get(session_key, [])
            if rid in self._results and self._results[rid].status == "running"
        ]

    def build_context_block(self, session_key: str) -> str:
        """Build the injection string for the agent's next turn.

        Shows completed/failed results (which are then drained) and running ones.
        Returns empty string if nothing to report.
        """
        lines: list[str] = []

        # Completed/failed results — drain them (show once)
        finished = self.drain(session_key)
        for r in finished:
            if r.status == "completed":
                paths = ", ".join(r.file_paths)
                lines.append(
                    f"[COMPLETED] {r.kind} generation \"{r.prompt[:50]}\" "
                    f"→ {paths}"
                )
            else:
                lines.append(
                    f"[FAILED] {r.kind} generation \"{r.prompt[:50]}\" "
                    f"→ {r.error}"
                )

        # Still running
        running = self.get_running(session_key)
        for r in running:
            elapsed = int(time.time() - r.created_at)
            lines.append(
                f"[RUNNING] {r.kind} generation \"{r.prompt[:50]}\" "
                f"({elapsed}s elapsed)"
            )

        if not lines:
            return ""

        return (
            "--- Background Generation Status ---\n"
            + "\n".join(lines)
            + "\n"
            + "For completed items: use send_message with media=[path] to deliver to the user.\n"
            + "---"
        )

    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all running workers for a session. Returns count cancelled."""
        ids = self._by_session.get(session_key, [])
        cancelled = 0
        for rid in list(ids):
            result = self._results.get(rid)
            if result and result.status == "running" and result._task:
                result._task.cancel()
                cancelled += 1
                result.status = "failed"
                result.error = "Cancelled by user"
                result.finished_at = time.time()
        return cancelled

    async def wait_running(self, session_key: str, timeout: float = 300) -> None:
        """Wait for all running workers in a session to finish (for CLI mode)."""
        tasks = []
        for rid in self._by_session.get(session_key, []):
            result = self._results.get(rid)
            if result and result.status == "running" and result._task:
                tasks.append(result._task)
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
