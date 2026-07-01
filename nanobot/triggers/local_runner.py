"""Gateway delivery loop for local triggers."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.triggers.local_session_turns import LOCAL_TRIGGER_META
from nanobot.triggers.local_store import LocalTriggerStore
from nanobot.triggers.local_types import LocalTrigger, TriggerDelivery
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY


async def run_local_trigger_queue(
    *,
    store: LocalTriggerStore,
    bus: MessageBus | None = None,
    submit_turn: Callable[[InboundMessage], Awaitable[OutboundMessage | None]] | None = None,
    poll_interval_s: float = 0.5,
    batch_size: int = 20,
) -> None:
    """Poll local trigger deliveries and publish them as normal inbound messages."""
    if bus is None and submit_turn is None:
        raise ValueError("run_local_trigger_queue requires bus or submit_turn")
    logger.info("Local trigger queue started")
    recovered = store.recover_processing_deliveries()
    if recovered:
        logger.warning(
            "Trigger: recovered {} interrupted delivery file(s) from processing",
            recovered,
        )
    while True:
        deliveries = store.claim_deliveries(limit=batch_size)
        if not deliveries:
            await asyncio.sleep(poll_interval_s)
            continue

        for delivery in deliveries:
            try:
                await _deliver_delivery(
                    store,
                    delivery,
                    bus=bus,
                    submit_turn=submit_turn,
                )
                store.complete_delivery(delivery)
            except asyncio.CancelledError as exc:
                store.retry_delivery(delivery, str(exc) or exc.__class__.__name__)
                raise
            except _TerminalDeliveryError as exc:
                store.record_delivery(
                    delivery.trigger_id,
                    status="error",
                    error=str(exc),
                    run_at_ms=delivery.created_at_ms,
                )
                store.complete_delivery(delivery)
                logger.warning(
                    "Trigger: dropped delivery {} for {}: {}",
                    delivery.id,
                    delivery.trigger_id,
                    exc,
                )
            except Exception as exc:
                error = str(exc) or exc.__class__.__name__
                retried = store.retry_delivery(delivery, error)
                store.record_delivery(
                    delivery.trigger_id,
                    status="error",
                    error=error,
                    run_at_ms=delivery.created_at_ms,
                )
                logger.exception(
                    "Trigger: failed delivery {} for {}{}",
                    delivery.id,
                    delivery.trigger_id,
                    "; queued retry" if retried else "; moved to failed queue",
                )


class _TerminalDeliveryError(RuntimeError):
    pass


async def _deliver_delivery(
    store: LocalTriggerStore,
    delivery: TriggerDelivery,
    *,
    bus: MessageBus | None,
    submit_turn: Callable[[InboundMessage], Awaitable[OutboundMessage | None]] | None,
) -> None:
    trigger = store.get(delivery.trigger_id)
    if trigger is None:
        raise _TerminalDeliveryError("trigger not found")
    if not trigger.enabled:
        raise _TerminalDeliveryError("trigger is disabled")

    msg = InboundMessage(
        channel=trigger.channel,
        sender_id=trigger.sender_id,
        chat_id=trigger.chat_id,
        content=delivery.content,
        metadata=_delivery_metadata(trigger, delivery),
        session_key_override=trigger.session_key,
    )
    if submit_turn is not None:
        await submit_turn(msg)
    else:
        if bus is None:
            raise RuntimeError("bus unavailable for local trigger delivery")
        await bus.publish_inbound(msg)
    store.record_delivery(
        trigger.id,
        status="ok",
        run_at_ms=delivery.created_at_ms,
    )


def _delivery_metadata(trigger: LocalTrigger, delivery: TriggerDelivery) -> dict[str, Any]:
    metadata = dict(trigger.origin_metadata or {})
    metadata[LOCAL_TRIGGER_META] = {
        "trigger_id": trigger.id,
        "trigger_name": trigger.name,
        "delivery_id": delivery.id,
        "created_at_ms": delivery.created_at_ms,
    }
    if trigger.channel == "websocket":
        metadata.pop(WEBUI_TURN_METADATA_KEY, None)
        metadata[WEBUI_TURN_METADATA_KEY] = f"trigger:{trigger.id}:{uuid.uuid4().hex}"
        source: dict[str, str] = {"kind": "local_trigger"}
        if trigger.name:
            source["label"] = trigger.name
        metadata[WEBUI_MESSAGE_SOURCE_METADATA_KEY] = source
    return metadata
