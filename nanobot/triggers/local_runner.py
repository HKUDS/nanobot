"""Gateway delivery loop for local triggers."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from nanobot.agent.automation_turns import AutomationTurnError
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.triggers.local_session_turns import LOCAL_TRIGGER_META
from nanobot.triggers.local_store import LocalTriggerStore
from nanobot.triggers.local_types import LocalTrigger, TriggerDelivery
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY


async def run_local_trigger_queue(
    *,
    store: LocalTriggerStore,
    submit_turn: Callable[[InboundMessage], Awaitable[OutboundMessage | None]] | None = None,
    is_channel_available: Callable[[str], bool] | None = None,
    poll_interval_s: float = 0.5,
    batch_size: int = 20,
) -> None:
    """Poll local trigger deliveries and submit them as session turns."""
    if submit_turn is None:
        raise ValueError("run_local_trigger_queue requires submit_turn")
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
                    submit_turn=submit_turn,
                    is_channel_available=is_channel_available,
                )
                store.complete_delivery(delivery)
            except asyncio.CancelledError as exc:
                store.retry_delivery(delivery, str(exc) or exc.__class__.__name__)
                _write_delivery_run_record(
                    store,
                    delivery,
                    status="interrupted",
                    error=str(exc) or exc.__class__.__name__,
                )
                raise
            except _TerminalDeliveryError as exc:
                store.record_delivery(
                    delivery.trigger_id,
                    status="error",
                    error=str(exc),
                    run_at_ms=delivery.created_at_ms,
                )
                _write_delivery_run_record(
                    store,
                    delivery,
                    status="error",
                    error=str(exc),
                )
                store.complete_delivery(delivery)
                logger.warning(
                    "Trigger: dropped delivery {} for {}: {}",
                    delivery.id,
                    delivery.trigger_id,
                    exc,
                )
            except AutomationTurnError as exc:
                error = str(exc) or exc.__class__.__name__
                store.record_delivery(
                    delivery.trigger_id,
                    status="error",
                    error=error,
                    run_at_ms=delivery.created_at_ms,
                )
                _write_delivery_run_record(
                    store,
                    delivery,
                    status="error",
                    error=error,
                )
                store.complete_delivery(delivery)
                logger.warning(
                    "Trigger: delivery {} for {} reached the agent but failed: {}",
                    delivery.id,
                    delivery.trigger_id,
                    error,
                )
            except Exception as exc:
                error = str(exc) or exc.__class__.__name__
                retried = store.retry_delivery(delivery, error)
                _write_delivery_run_record(
                    store,
                    delivery,
                    status="retrying" if retried else "error",
                    error=error,
                )
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
    submit_turn: Callable[[InboundMessage], Awaitable[OutboundMessage | None]],
    is_channel_available: Callable[[str], bool] | None = None,
) -> None:
    trigger = store.get(delivery.trigger_id)
    if trigger is None:
        raise _TerminalDeliveryError("trigger not found")
    if not trigger.enabled:
        raise _TerminalDeliveryError("trigger is disabled")
    if is_channel_available is not None and not is_channel_available(trigger.channel):
        raise _TerminalDeliveryError(f"target channel is not enabled: {trigger.channel}")

    store.write_delivery_run_record(delivery, trigger=trigger, status="processing")
    msg = InboundMessage(
        channel=trigger.channel,
        sender_id=trigger.sender_id,
        chat_id=trigger.chat_id,
        content=delivery.content,
        metadata=_delivery_metadata(trigger, delivery),
        session_key_override=trigger.session_key,
    )
    response = await submit_turn(msg)
    store.record_delivery(
        trigger.id,
        status="ok",
        run_at_ms=delivery.created_at_ms,
    )
    _write_delivery_run_record(
        store,
        delivery,
        trigger=trigger,
        status="ok",
        response=response.content if response else "",
    )


def _write_delivery_run_record(
    store: LocalTriggerStore,
    delivery: TriggerDelivery,
    *,
    status: str,
    trigger: LocalTrigger | None = None,
    error: str | None = None,
    response: str | None = None,
) -> None:
    try:
        store.write_delivery_run_record(
            delivery,
            trigger=trigger,
            status=status,
            error=error,
            response=response,
        )
    except Exception:
        logger.exception(
            "Trigger: failed to write run record for delivery {}",
            delivery.id,
        )


def _delivery_metadata(trigger: LocalTrigger, delivery: TriggerDelivery) -> dict[str, Any]:
    metadata = dict(trigger.origin_metadata or {})
    metadata[LOCAL_TRIGGER_META] = {
        "trigger_id": trigger.id,
        "trigger_name": trigger.name,
        "delivery_id": delivery.id,
        "created_at_ms": delivery.created_at_ms,
        "persist_content": _history_content(trigger, delivery),
    }
    if trigger.channel == "websocket":
        metadata.pop(WEBUI_TURN_METADATA_KEY, None)
        metadata[WEBUI_TURN_METADATA_KEY] = f"trigger:{trigger.id}:{uuid.uuid4().hex}"
        source: dict[str, str] = {"kind": "local_trigger"}
        if trigger.name:
            source["label"] = trigger.name
        metadata[WEBUI_MESSAGE_SOURCE_METADATA_KEY] = source
    return metadata


def _history_content(trigger: LocalTrigger, delivery: TriggerDelivery) -> str:
    label = trigger.name.strip() if trigger.name else trigger.id
    return f"Local trigger received: {label}\n\n{delivery.content}"
