"""Coordination for local trigger turns."""

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
        publish_inbound: Callable[[InboundMessage], Awaitable[None]],
        dispatch: Callable[[InboundMessage], Awaitable[object]],
        is_running: Callable[[], bool],
        deferred_queues: dict[str, list[InboundMessage]] | None = None,
    ) -> None:
        super().__init__(
            publish_inbound=publish_inbound,
            dispatch=dispatch,
            is_running=is_running,
            turn_id=lambda msg: local_trigger_delivery_id(msg.metadata),
            pending_id=_local_trigger_id,
            should_defer_turn=_should_defer_local_trigger_turn,
            missing_id_error="local trigger turn metadata must include a delivery_id",
            duplicate_id_error=lambda delivery_id: (
                f"local trigger delivery {delivery_id!r} is already pending"
            ),
            deferred_queues=deferred_queues,
        )

    def pending_trigger_ids_for_session(self, session_key: str) -> set[str]:
        """Return local triggers waiting for or running in *session_key*."""
        return self.pending_ids_for_session(session_key)


def _should_defer_local_trigger_turn(
    msg: InboundMessage,
    session_key: str,
    active_session_keys: Iterable[str],
) -> bool:
    return local_trigger(msg.metadata) is not None and session_key in active_session_keys


def _local_trigger_id(msg: InboundMessage) -> str | None:
    trigger = local_trigger(msg.metadata)
    if not trigger:
        return None
    value = trigger.get("trigger_id")
    return value if isinstance(value, str) and value else None
