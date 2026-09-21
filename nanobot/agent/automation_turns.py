"""Shared coordination for session-bound automation turns."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable, Iterable

from nanobot.bus.events import InboundMessage, OutboundMessage


class AutomationTurnError(RuntimeError):
    """Raised when an automation turn reaches the agent and finishes with an error."""


class AutomationTurnCoordinator:
    """Manage automation turns without mixing them into live injections."""

    def __init__(
        self,
        *,
        enqueue: Callable[[InboundMessage], None],
        turn_id: Callable[[InboundMessage], str | None],
        pending_id: Callable[[InboundMessage], str | None],
        should_defer_turn: Callable[[InboundMessage, str, Iterable[str]], bool],
        missing_id_error: str,
        duplicate_id_error: Callable[[str], str],
        deferred_queues: dict[str, list[InboundMessage]] | None = None,
    ) -> None:
        self._enqueue = enqueue
        self._turn_id = turn_id
        self._pending_id = pending_id
        self._should_defer_turn = should_defer_turn
        self._missing_id_error = missing_id_error
        self._duplicate_id_error = duplicate_id_error
        self.deferred_queues = deferred_queues if deferred_queues is not None else {}
        self._waiters: dict[str, asyncio.Future[OutboundMessage | None]] = {}
        self._pending_messages_by_turn_id: dict[str, InboundMessage] = {}

    def owns_turn(self, msg: InboundMessage) -> bool:
        """Whether this message requires an independent automation completion."""
        return bool(self._turn_id(msg))

    async def submit(self, msg: InboundMessage) -> OutboundMessage | None:
        """Submit an automation turn and wait for its session response."""
        turn_id = self._turn_id(msg)
        if not turn_id:
            raise ValueError(self._missing_id_error)
        if turn_id in self._waiters:
            raise RuntimeError(self._duplicate_id_error(turn_id))

        loop = asyncio.get_running_loop()
        future: asyncio.Future[OutboundMessage | None] = loop.create_future()
        self._waiters[turn_id] = future
        self._pending_messages_by_turn_id[turn_id] = msg
        try:
            self._enqueue(msg)
            try:
                return await future
            except asyncio.CancelledError:
                raise
            except AutomationTurnError:
                raise
            except Exception as exc:
                raise AutomationTurnError(str(exc) or exc.__class__.__name__) from exc
        finally:
            self._waiters.pop(turn_id, None)
            self._pending_messages_by_turn_id.pop(turn_id, None)

    def defer_if_active(
        self,
        msg: InboundMessage,
        *,
        session_key: str,
        active_session_keys: Iterable[str],
    ) -> bool:
        """Defer an automation turn when its target session is already active."""
        if not self._should_defer_turn(msg, session_key, active_session_keys):
            return False
        pending_msg = msg
        if session_key != msg.session_key:
            pending_msg = dataclasses.replace(
                msg,
                session_key_override=session_key,
            )
        self.deferred_queues.setdefault(session_key, []).append(pending_msg)
        return True

    def complete(
        self,
        msg: InboundMessage,
        *,
        response: OutboundMessage | None = None,
        error: BaseException | None = None,
    ) -> None:
        turn_id = self._turn_id(msg)
        if not turn_id:
            return
        future = self._waiters.get(turn_id)
        if future is None or future.done():
            return
        if error is not None:
            if isinstance(error, asyncio.CancelledError):
                error = AutomationTurnError(str(error) or error.__class__.__name__)
            future.set_exception(error)
        else:
            future.set_result(response)

    def pending_ids_for_session(self, session_key: str) -> set[str]:
        """Return automation IDs that are waiting for or running in *session_key*."""
        pending_ids: set[str] = set()
        for msg in self.deferred_queues.get(session_key, []):
            pending_id = self._pending_id(msg)
            if pending_id:
                pending_ids.add(pending_id)
        for msg in self._pending_messages_by_turn_id.values():
            if msg.session_key != session_key:
                continue
            pending_id = self._pending_id(msg)
            if pending_id:
                pending_ids.add(pending_id)
        return pending_ids
