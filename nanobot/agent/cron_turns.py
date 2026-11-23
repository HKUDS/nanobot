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
        enqueue: Callable[[InboundMessage], Awaitable[None]],
    ) -> None:
        super().__init__(
            enqueue=enqueue,
            turn_id=lambda msg: cron_run_id(msg.metadata),
            pending_id=_cron_job_id,
            should_defer_turn=lambda msg: defer_cron_until_session_idle(msg.metadata),
            missing_id_error="cron turn metadata must include a run_id",
            duplicate_id_error=lambda run_id: f"cron run {run_id!r} is already pending",
        )

    def pending_job_ids_for_session(
        self, session_key: str, deferred: Iterable[InboundMessage],
    ) -> set[str]:
        """Return cron jobs that are waiting for or running in *session_key*."""
        return self.pending_ids_for_session(session_key, deferred)


def _cron_job_id(msg: InboundMessage) -> str | None:
    trigger = cron_trigger(msg.metadata)
    if not trigger:
        return None
    value = trigger.get("job_id")
    return value if isinstance(value, str) and value else None
