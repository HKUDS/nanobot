"""Gateway delivery loop for local external triggers."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.triggers.session_turns import EXTERNAL_TRIGGER_META
from nanobot.triggers.store import ExternalTriggerStore
from nanobot.triggers.types import ExternalTrigger, TriggerDelivery
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY


async def run_external_trigger_queue(
    *,
    store: ExternalTriggerStore,
    bus: MessageBus,
    poll_interval_s: float = 0.5,
    batch_size: int = 20,
) -> None:
    """Poll local trigger deliveries and publish them as normal inbound messages."""
    logger.info("External trigger queue started")
    while True:
        deliveries = store.claim_deliveries(limit=batch_size)
        if not deliveries:
            await asyncio.sleep(poll_interval_s)
            continue

        for delivery in deliveries:
            try:
                await _publish_delivery(store, bus, delivery)
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


async def _publish_delivery(
    store: ExternalTriggerStore,
    bus: MessageBus,
    delivery: TriggerDelivery,
) -> None:
    trigger = store.get(delivery.trigger_id)
    if trigger is None:
        raise _TerminalDeliveryError("trigger not found")
    if not trigger.enabled:
        raise _TerminalDeliveryError("trigger is disabled")

    await bus.publish_inbound(
        InboundMessage(
            channel=trigger.channel,
            sender_id=trigger.sender_id,
            chat_id=trigger.chat_id,
            content=delivery.content,
            metadata=_delivery_metadata(trigger, delivery),
            session_key_override=trigger.session_key,
        )
    )
    store.record_delivery(
        trigger.id,
        status="ok",
        run_at_ms=delivery.created_at_ms,
    )


def _delivery_metadata(trigger: ExternalTrigger, delivery: TriggerDelivery) -> dict[str, Any]:
    metadata = dict(trigger.origin_metadata or {})
    metadata[EXTERNAL_TRIGGER_META] = {
        "trigger_id": trigger.id,
        "trigger_name": trigger.name,
        "delivery_id": delivery.id,
        "created_at_ms": delivery.created_at_ms,
    }
    if trigger.channel == "websocket":
        metadata.pop(WEBUI_TURN_METADATA_KEY, None)
        metadata[WEBUI_TURN_METADATA_KEY] = f"trigger:{trigger.id}:{uuid.uuid4().hex}"
        source: dict[str, str] = {"kind": "trigger"}
        if trigger.name:
            source["label"] = trigger.name
        metadata[WEBUI_MESSAGE_SOURCE_METADATA_KEY] = source
    return metadata
