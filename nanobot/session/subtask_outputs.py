"""Bounded public subtask snapshots owned by the existing parent session.

This is an observer, not a scheduler or persistence service. Normal session saves
carry these records; transient session policy remains authoritative.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal, TypedDict, cast
from weakref import WeakValueDictionary

from nanobot.session.manager import Session, SessionManager

SUBTASK_OUTPUTS_KEY = "subtask_outputs.v1"
MAX_SUBTASKS = 32
MAX_OUTPUT = 12_000
MAX_TOOLS = 20
_LIVE: WeakValueDictionary[str, SubtaskOutput] = WeakValueDictionary()
_STATES = frozenset({"queued", "running", "completed", "failed", "cancelled", "interrupted"})

SubtaskState = Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]


class SubtaskRecord(TypedDict):
    task_id: str
    turn_id: str | None
    label: str
    runtime_id: str
    state: SubtaskState
    revision: int
    iteration: int
    elapsed_ms: int
    started_ms: int
    output: str
    tools: list[str]
    truncated: bool


def public_subtasks(metadata: object) -> list[dict[str, Any]]:
    """Allowlist fields, bound old metadata and invalidate stale liveness."""
    if not isinstance(metadata, dict):
        return []
    raw = cast(dict[str, Any], metadata).get(SUBTASK_OUTPUTS_KEY)
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for value in cast(list[object], raw)[-MAX_SUBTASKS:]:
        if not isinstance(value, dict):
            continue
        row = cast(dict[str, Any], value)
        task_id, state = row.get("task_id"), row.get("state")
        if not isinstance(task_id, str) or not task_id or not isinstance(state, str) or state not in _STATES:
            continue
        observer = _LIVE.get(str(row.get("runtime_id") or ""))
        if state in {"queued", "running"} and (observer is None or not observer.enabled):
            state = "interrupted"
        elapsed_ms = _number(row.get("elapsed_ms"))
        started_ms = _number(row.get("started_ms"))
        if state in {"queued", "running"} and started_ms:
            elapsed_ms = max(elapsed_ms, int(time.time() * 1000) - started_ms)
        tools = row.get("tools")
        result.append({
            "task_id": task_id[:64], "turn_id": str(row.get("turn_id") or "")[:128],
            "label": str(row.get("label") or "")[:120], "state": state,
            "revision": _number(row.get("revision")), "iteration": _number(row.get("iteration")),
            "elapsed_ms": elapsed_ms,
            "output": str(row.get("output") or "")[-MAX_OUTPUT:],
            "truncated": row.get("truncated") is True,
            "tools": [item[:80] for item in cast(list[object], tools)[-MAX_TOOLS:] if isinstance(item, str)]
            if isinstance(tools, list) else [],
        })
    return result


def _number(value: object) -> int:
    return max(0, min(value, 2**53 - 1)) if isinstance(value, int) and not isinstance(value, bool) else 0


class SubtaskOutput:
    """One execution's observer. Never creates, reloads or saves a parent session."""

    def __init__(self, sessions: SessionManager | None, session_key: str | None,
                 task_id: str, label: str, turn_id: str | None) -> None:
        self._sessions = sessions
        self._parent: Session | None = (
            sessions.get_cached(session_key) if sessions is not None and session_key else None
        )
        self._started = time.monotonic()
        self._row: SubtaskRecord = {
            "task_id": task_id, "turn_id": turn_id, "label": label[:120],
            "runtime_id": uuid.uuid4().hex, "state": "queued", "revision": 0,
            "iteration": 0, "elapsed_ms": 0, "output": "", "tools": [], "truncated": False,
            "started_ms": int(time.time() * 1000),
        }
        _LIVE[self._row["runtime_id"]] = self
        self.update()

    @property
    def enabled(self) -> bool:
        return (self._parent is not None and self._sessions is not None
                and self._sessions.get_cached(self._parent.key) is self._parent)

    def update(self, *, state: SubtaskState | None = None, iteration: int | None = None,
               output: str | None = None, tool: str | None = None) -> None:
        parent, sessions = self._parent, self._sessions
        # Invalidation revokes this observer; late callbacks cannot revive it.
        if parent is None or sessions is None or sessions.get_cached(parent.key) is not parent:
            return
        if state is not None:
            self._row["state"] = state
        if iteration is not None:
            self._row["iteration"] = iteration
        if output is not None:
            self._row["output"] = output[-MAX_OUTPUT:]
            self._row["truncated"] = len(output) > MAX_OUTPUT
        if tool is not None:
            self._row["tools"] = [*self._row["tools"], tool[:80]][-MAX_TOOLS:]
        self._row["revision"] += 1
        self._row["elapsed_ms"] = int((time.monotonic() - self._started) * 1000)
        previous = parent.metadata.get(SUBTASK_OUTPUTS_KEY)
        candidates = cast(list[object], previous) if isinstance(previous, list) else []
        rows: list[dict[str, Any]] = []
        replaced = False
        for item in candidates:
            if isinstance(item, dict):
                row = cast(dict[str, Any], item)
                if row.get("task_id") == self._row["task_id"]:
                    rows.append(dict(self._row))
                    replaced = True
                else:
                    rows.append(row)
        if not replaced:
            rows.append(dict(self._row))
        parent.metadata[SUBTASK_OUTPUTS_KEY] = rows[-MAX_SUBTASKS:]
