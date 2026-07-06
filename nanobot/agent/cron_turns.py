"""Coordination for scheduled cron turns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from nanobot.agent.automation_turns import AutomationTurnCoordinator
from nanobot.bus.events import InboundMessage
from nanobot.cron.session_turns import (
    cron_run_id,
    cron_trigger,
    defer_cron_until_session_idle,
)


class CronTurnCoordinator(AutomationTurnCoordinator):
    """Manage scheduled cron turns without mixing them into live injections."""

    def __init__(
        self,
        *,
        publish_inbound: Callable[[InboundMessage], Awaitable[None]],
        dispatch: Callable[[InboundMessage], Awaitable[object]],
        is_running: Callable[[], bool],
        deferred_queues: dict[str, list[InboundMessage]] | None = None,
    ) -> None:
        super().__init__(
            publish_inbound=publish_inbound,
            dispatch=dispatch,
            is_running=is_running,
            turn_id=lambda msg: cron_run_id(msg.metadata),
            pending_id=_cron_job_id,
            should_defer_turn=_should_defer_cron_turn,
            missing_id_error="cron turn metadata must include a run_id",
            duplicate_id_error=lambda run_id: f"cron run {run_id!r} is already pending",
            deferred_queues=deferred_queues,
        )

    def pending_job_ids_for_session(self, session_key: str) -> set[str]:
        """Return cron jobs that are waiting for or running in *session_key*."""
        return self.pending_ids_for_session(session_key)


def _should_defer_cron_turn(
    msg: InboundMessage,
    session_key: str,
    active_session_keys: Iterable[str],
) -> bool:
    return defer_cron_until_session_idle(msg.metadata) and session_key in active_session_keys


def _cron_job_id(msg: InboundMessage) -> str | None:
    trigger = cron_trigger(msg.metadata)
    if not trigger:
        return None
    value = trigger.get("job_id")
    return value if isinstance(value, str) and value else None
