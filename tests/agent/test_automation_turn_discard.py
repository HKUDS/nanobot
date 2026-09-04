from __future__ import annotations

import asyncio

import pytest

from nanobot.agent.automation_turns import (
    AutomationTurnCoordinator,
    AutomationTurnDiscardedError,
)
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


def _message(session_key: str, run_id: str) -> InboundMessage:
    return InboundMessage(
        channel="system",
        sender_id="cron",
        chat_id=session_key,
        content=run_id,
        session_key_override=session_key,
        metadata={"run_id": run_id},
    )


def _coordinator(bus: MessageBus, deferred: dict[str, list[InboundMessage]]) -> AutomationTurnCoordinator:
    return AutomationTurnCoordinator(
        publish_inbound=bus.publish_inbound,
        dispatch=lambda _msg: asyncio.sleep(0),
        is_running=lambda: True,
        turn_id=lambda msg: msg.metadata.get("run_id"),
        pending_id=lambda msg: msg.metadata.get("run_id"),
        should_defer_turn=lambda _msg, key, active: key in active,
        missing_id_error="missing run id",
        duplicate_id_error=lambda run_id: f"duplicate {run_id}",
        deferred_queues=deferred,
    )


@pytest.mark.asyncio
async def test_discard_session_drops_deferred_turn_and_unblocks_waiter() -> None:
    bus = MessageBus()
    deferred: dict[str, list[InboundMessage]] = {}
    coordinator = _coordinator(bus, deferred)
    msg = _message("websocket:chat", "run-1")

    submit_task = asyncio.create_task(coordinator.submit(msg))
    await asyncio.sleep(0)
    assert await bus.consume_inbound() is msg
    assert coordinator.defer_if_active(
        msg, session_key=msg.session_key, active_session_keys={msg.session_key}
    )

    assert coordinator.discard_session(msg.session_key) == 1
    with pytest.raises(AutomationTurnDiscardedError):
        await submit_task
    assert msg.session_key not in deferred
    assert bus.inbound.empty()


def test_discard_session_ignores_unrelated_session() -> None:
    bus = MessageBus()
    deferred = {"websocket:other": [_message("websocket:other", "run-2")]}
    coordinator = _coordinator(bus, deferred)

    assert coordinator.discard_session("websocket:chat") == 0
    assert "websocket:other" in deferred
