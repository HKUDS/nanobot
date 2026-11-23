from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from nanobot.agent.automation_turns import AutomationTurnCoordinator
from nanobot.bus.events import InboundMessage
from nanobot.triggers.local_session_turns import local_trigger, local_trigger_delivery_id


class LocalTriggerTurnCoordinator(AutomationTurnCoordinator):
    """Manage local trigger turns without mixing them into live injections."""

    def __init__(
        self,
        *,
        enqueue: Callable[[InboundMessage], Awaitable[None]],
    ) -> None:
        super().__init__(
            enqueue=enqueue,
            turn_id=lambda msg: local_trigger_delivery_id(msg.metadata),
            pending_id=_local_trigger_id,
            should_defer_turn=lambda msg: local_trigger(msg.metadata) is not None,
            missing_id_error="local trigger turn metadata must include a delivery_id",
            duplicate_id_error=lambda delivery_id: (
                f"local trigger delivery {delivery_id!r} is already pending"
            ),
        )

    def pending_trigger_ids_for_session(
        self, session_key: str, deferred: Iterable[InboundMessage],
    ) -> set[str]:
        """Return local triggers waiting for or running in *session_key*."""
        return self.pending_ids_for_session(session_key, deferred)


def _local_trigger_id(msg: InboundMessage) -> str | None:
    trigger = local_trigger(msg.metadata)
    if not trigger:
        return None
    value = trigger.get("trigger_id")
    return value if isinstance(value, str) and value else None
