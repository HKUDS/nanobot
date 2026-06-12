"""Coordination for scheduled cron turns."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cron.session_turns import cron_run_id, defer_cron_until_session_idle


class CronTurnCoordinator:
    """Manage scheduled cron turns without mixing them into live injections."""

    def __init__(
        self,
        *,
        publish_inbound: Callable[[InboundMessage], Awaitable[None]],
        dispatch: Callable[[InboundMessage], Awaitable[object]],
        is_running: Callable[[], bool],
    ) -> None:
        self._publish_inbound = publish_inbound
        self._dispatch = dispatch
        self._is_running = is_running
        self.deferred_queues: dict[str, list[InboundMessage]] = {}
        self._waiters: dict[str, asyncio.Future[OutboundMessage | None]] = {}

    async def submit(self, msg: InboundMessage) -> OutboundMessage | None:
        """Submit a scheduled cron turn and wait for its session response."""
        run_id = cron_run_id(msg.metadata)
        if not run_id:
            raise ValueError("cron turn metadata must include a run_id")
        if run_id in self._waiters:
            raise RuntimeError(f"cron run {run_id!r} is already pending")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[OutboundMessage | None] = loop.create_future()
        self._waiters[run_id] = future
        try:
            if self._is_running():
                await self._publish_inbound(msg)
            else:
                await self._dispatch(msg)
            return await future
        finally:
            self._waiters.pop(run_id, None)

    def should_defer(
        self,
        msg: InboundMessage,
        *,
        session_key: str,
        active_session_keys: Iterable[str],
    ) -> bool:
        return (
            defer_cron_until_session_idle(msg.metadata)
            and session_key in active_session_keys
        )

    def complete(
        self,
        msg: InboundMessage,
        *,
        response: OutboundMessage | None = None,
        error: BaseException | None = None,
    ) -> None:
        run_id = cron_run_id(msg.metadata)
        if not run_id:
            return
        future = self._waiters.get(run_id)
        if future is None or future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(response)

    def defer(self, session_key: str, msg: InboundMessage) -> None:
        self.deferred_queues.setdefault(session_key, []).append(msg)

    async def publish_next_deferred(self, session_key: str) -> None:
        queue = self.deferred_queues.get(session_key)
        if not queue:
            return
        msg = queue.pop(0)
        if not queue:
            self.deferred_queues.pop(session_key, None)
        await self._publish_inbound(msg)
