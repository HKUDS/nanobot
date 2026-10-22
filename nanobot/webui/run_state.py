"""Gateway-local, versioned projection of admitted execution owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Literal, TypedDict

from nanobot.bus.events import INBOUND_META_TURN_ID
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import TurnExecutionChanged
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.webui.session_identity import is_webui_session_key, webui_session_key

RunPhase = Literal["queued", "running", "stopping"]


class ServerRun(TypedDict):
    run_id: str
    turn_id: str | None
    phase: RunPhase
    started_at: float | None


class ServerRunSnapshot(TypedDict):
    instance_id: str
    revision: int
    runs: list[ServerRun]


@dataclass
class _Run:
    execution_id: str
    turn_id: str | None
    execution_session_key: str
    phase: RunPhase = "queued"
    started_at: float | None = None

    def payload(self) -> ServerRun:
        return ServerRun(
            run_id=self.execution_id, turn_id=self.turn_id,
            phase=self.phase, started_at=self.started_at,
        )


RunStateListener = Callable[[str, ServerRunSnapshot], None]


class RunStateAuthority:
    """Observe the scheduler's facts; never schedule work or infer it from history.

    Mutation, snapshot and synchronous notification share one boundary. Listeners
    may only enqueue output, never perform I/O. HTTP readers can use snapshots
    from worker threads without holding this lock across history or network work.
    """

    def __init__(self, bus: MessageBus, instance_id: str) -> None:
        self.instance_id = instance_id
        self._revision = 0
        self._runs: dict[str, dict[str, _Run]] = {}
        self._listeners: list[RunStateListener] = []
        self._lock = RLock()
        self._unsubscribe = bus.subscribe(self._execution_changed, TurnExecutionChanged)

    def close(self) -> None:
        self._unsubscribe()
        with self._lock:
            self._listeners.clear()

    def subscribe(self, listener: RunStateListener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)
        return unsubscribe

    def snapshot(self, session_key: str) -> ServerRunSnapshot:
        with self._lock:
            return self._snapshot(session_key)

    def _snapshot(self, session_key: str) -> ServerRunSnapshot:
        return ServerRunSnapshot(
            instance_id=self.instance_id,
            revision=self._revision,
            runs=[run.payload() for run in self._runs.get(session_key, {}).values()],
        )

    def _changed(self, session_key: str) -> None:
        self._revision += 1
        for listener in tuple(self._listeners):
            listener(session_key, self._snapshot(session_key))

    def execution_session_key(self, session_key: str, run_id: str) -> str | None:
        """Resolve an observed owner's execution scope without mutating intent."""
        with self._lock:
            run = self._runs.get(session_key, {}).get(run_id)
            return run.execution_session_key if run is not None else None

    def _queued(
        self, session_key: str, run_id: str, turn_id: str | None,
        execution_session_key: str,
    ) -> None:
        if run_id in self._runs.get(session_key, {}):
            return
        self._runs.setdefault(session_key, {})[run_id] = _Run(run_id, turn_id, execution_session_key)
        self._changed(session_key)

    def _finish(self, session_key: str, run_id: str) -> None:
        runs = self._runs.get(session_key)
        if not runs or run_id not in runs:
            return
        runs.pop(run_id)
        if not runs:
            self._runs.pop(session_key, None)
        self._changed(session_key)

    def _execution_changed(self, event: TurnExecutionChanged) -> None:
        context = event.context
        session_key = context.session_key
        if session_key == UNIFIED_SESSION_KEY and context.channel == "websocket":
            session_key = webui_session_key(context.chat_id)
        if not is_webui_session_key(session_key):
            return
        with self._lock:
            if event.phase == "queued":
                turn_id = context.metadata.get(INBOUND_META_TURN_ID)
                self._queued(
                    session_key, event.execution_id,
                    turn_id if isinstance(turn_id, str) and turn_id else None,
                    context.session_key,
                )
                return
            if event.phase == "injected" or event.phase == "rejected" or event.phase == "exited":
                self._finish(session_key, event.execution_id)
                return
            run = self._runs.get(session_key, {}).get(event.execution_id)
            if run is None or run.phase == "stopping":
                return
            if run.phase == event.phase:
                return
            run.phase = event.phase
            if event.started_at is not None:
                run.started_at = event.started_at
            self._changed(session_key)
