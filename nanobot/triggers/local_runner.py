"""Gateway delivery loop for local triggers."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, TypeVar

from loguru import logger

from nanobot.agent.automation_turns import (
    AutomationTurnAcceptedCancellation,
    AutomationTurnError,
)
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.triggers.local_session_turns import LOCAL_TRIGGER_META
from nanobot.triggers.local_store import LocalTriggerStore
from nanobot.triggers.local_types import LocalTrigger, TriggerDelivery
from nanobot.utils.cancellation import shield_and_drain
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY

_T = TypeVar("_T")


async def run_local_trigger_queue(
    *,
    store: LocalTriggerStore,
    submit_turn: Callable[[InboundMessage], Awaitable[OutboundMessage | None]] | None = None,
    is_channel_enabled: Callable[[str], bool],
    poll_interval_s: float = 0.5,
    batch_size: int = 20,
) -> None:
    """Poll local trigger deliveries and submit them as session turns."""
    if submit_turn is None:
        raise ValueError("run_local_trigger_queue requires submit_turn")
    logger.info("Local trigger queue started")
    recovered = await shield_and_drain(asyncio.to_thread(store.recover_processing_deliveries))
    if recovered:
        logger.warning(
            "Trigger: recovered {} interrupted delivery file(s) from processing",
            recovered,
        )
    while True:
        deliveries = await shield_and_drain(
            asyncio.to_thread(store.claim_deliveries, limit=batch_size)
        )
        if not deliveries:
            await asyncio.sleep(poll_interval_s)
            continue

        for delivery in deliveries:
            try:
                await _deliver_delivery(
                    store,
                    delivery,
                    submit_turn=submit_turn,
                    is_channel_enabled=is_channel_enabled,
                )
            except _DeliverySettledOnCancellation:
                raise
            except asyncio.CancelledError as exc:
                error = str(exc) or exc.__class__.__name__
                await shield_and_drain(asyncio.to_thread(store.retry_delivery, delivery, error))
                await _write_delivery_run_record(
                    store,
                    delivery,
                    status="interrupted",
                    error=error,
                )
                raise
            except _TerminalDeliveryError as exc:
                await _await_delivery_settlement(
                    _settle_failed_delivery(store, delivery, error=str(exc)),
                    store=store,
                    delivery=delivery,
                )
                logger.warning(
                    "Trigger: dropped delivery {} for {}: {}",
                    delivery.id,
                    delivery.trigger_id,
                    exc,
                )
            except AutomationTurnError as exc:
                error = str(exc) or exc.__class__.__name__
                await _await_delivery_settlement(
                    _settle_failed_delivery(store, delivery, error=error),
                    store=store,
                    delivery=delivery,
                )
                logger.warning(
                    "Trigger: delivery {} for {} reached the agent but failed: {}",
                    delivery.id,
                    delivery.trigger_id,
                    error,
                )
            except Exception as exc:
                error = str(exc) or exc.__class__.__name__
                retried = await _await_delivery_settlement(
                    _settle_retryable_delivery(store, delivery, error=error),
                    store=store,
                    delivery=delivery,
                )
                logger.exception(
                    "Trigger: failed delivery {} for {}{}",
                    delivery.id,
                    delivery.trigger_id,
                    "; queued retry" if retried else "; moved to failed queue",
                )


class _TerminalDeliveryError(RuntimeError):
    pass


class _DeliverySettledOnCancellation(asyncio.CancelledError):
    """Cancellation reported only after an already-submitted delivery is settled."""


async def _deliver_delivery(
    store: LocalTriggerStore,
    delivery: TriggerDelivery,
    *,
    submit_turn: Callable[[InboundMessage], Awaitable[OutboundMessage | None]],
    is_channel_enabled: Callable[[str], bool],
) -> None:
    trigger = await asyncio.to_thread(store.get, delivery.trigger_id)
    if trigger is None:
        raise _TerminalDeliveryError("trigger not found")
    if not trigger.enabled:
        raise _TerminalDeliveryError("trigger is disabled")
    if not is_channel_enabled(trigger.channel):
        raise _TerminalDeliveryError(f"target channel is not enabled: {trigger.channel}")

    await shield_and_drain(
        asyncio.to_thread(
            store.write_delivery_run_record,
            delivery,
            trigger=trigger,
            status="processing",
        )
    )
    msg = InboundMessage(
        channel=trigger.channel,
        sender_id=trigger.sender_id,
        chat_id=trigger.chat_id,
        content=delivery.content,
        metadata=_delivery_metadata(trigger, delivery),
        session_key_override=trigger.session_key,
    )
    try:
        response = await submit_turn(msg)
    except AutomationTurnAcceptedCancellation:
        try:
            await _await_delivery_settlement(
                _settle_accepted_delivery(store, delivery, trigger=trigger),
                store=store,
                delivery=delivery,
            )
        except _DeliverySettledOnCancellation:
            raise
        except Exception:
            logger.exception(
                "Trigger: failed to persist accepted delivery {}; dropping retry",
                delivery.id,
            )
            with suppress(Exception):
                await shield_and_drain(asyncio.to_thread(store.complete_delivery, delivery))
        raise _DeliverySettledOnCancellation from None

    try:
        await _await_delivery_settlement(
            _settle_submitted_delivery(store, delivery, trigger=trigger, response=response),
            store=store,
            delivery=delivery,
        )
    except Exception:
        logger.exception(
            "Trigger: failed to persist status for submitted delivery {}; dropping retry",
            delivery.id,
        )
        with suppress(Exception):
            await shield_and_drain(asyncio.to_thread(store.complete_delivery, delivery))


async def _await_delivery_settlement(
    operation: Awaitable[_T],
    *,
    store: LocalTriggerStore,
    delivery: TriggerDelivery,
) -> _T:
    settlement = asyncio.ensure_future(operation)
    try:
        return await asyncio.shield(settlement)
    except asyncio.CancelledError:
        while not settlement.done():
            try:
                await asyncio.shield(settlement)
            except asyncio.CancelledError:
                continue
        try:
            settlement.result()
        except Exception:
            logger.exception(
                "Trigger: failed to settle delivery {} during cancellation",
                delivery.id,
            )
            completion = asyncio.create_task(
                shield_and_drain(asyncio.to_thread(store.complete_delivery, delivery))
            )
            while not completion.done():
                try:
                    await asyncio.shield(completion)
                except asyncio.CancelledError:
                    continue
            with suppress(Exception):
                completion.result()
        raise _DeliverySettledOnCancellation from None


async def _settle_failed_delivery(
    store: LocalTriggerStore,
    delivery: TriggerDelivery,
    *,
    error: str,
) -> None:
    await _write_delivery_run_record(
        store,
        delivery,
        status="error",
        error=error,
    )
    await shield_and_drain(asyncio.to_thread(store.complete_delivery, delivery))
    # Publish the terminal status only after the durable delivery state is settled.
    await shield_and_drain(
        asyncio.to_thread(
            store.record_delivery,
            delivery.trigger_id,
            status="error",
            error=error,
            run_at_ms=delivery.created_at_ms,
        )
    )


async def _settle_retryable_delivery(
    store: LocalTriggerStore,
    delivery: TriggerDelivery,
    *,
    error: str,
) -> bool:
    retried = await shield_and_drain(asyncio.to_thread(store.retry_delivery, delivery, error))
    await _write_delivery_run_record(
        store,
        delivery,
        status="retrying" if retried else "error",
        error=error,
    )
    await shield_and_drain(
        asyncio.to_thread(
            store.record_delivery,
            delivery.trigger_id,
            status="error",
            error=error,
            run_at_ms=delivery.created_at_ms,
        )
    )
    return retried


async def _settle_accepted_delivery(
    store: LocalTriggerStore,
    delivery: TriggerDelivery,
    *,
    trigger: LocalTrigger,
) -> None:
    """Commit an accepted delivery without claiming the agent turn completed."""
    await _write_delivery_run_record(
        store,
        delivery,
        trigger=trigger,
        status="accepted",
    )
    await shield_and_drain(asyncio.to_thread(store.complete_delivery, delivery))
    await shield_and_drain(
        asyncio.to_thread(
            store.record_delivery,
            trigger.id,
            status="ok",
            run_at_ms=delivery.created_at_ms,
        )
    )


async def _settle_submitted_delivery(
    store: LocalTriggerStore,
    delivery: TriggerDelivery,
    *,
    trigger: LocalTrigger,
    response: OutboundMessage | None,
) -> None:
    await _write_delivery_run_record(
        store,
        delivery,
        trigger=trigger,
        status="ok",
        response=response.content if response else "",
    )
    await shield_and_drain(asyncio.to_thread(store.complete_delivery, delivery))
    # last_status is the externally visible commit marker for a settled delivery.
    await shield_and_drain(
        asyncio.to_thread(
            store.record_delivery,
            trigger.id,
            status="ok",
            run_at_ms=delivery.created_at_ms,
        )
    )


async def _write_delivery_run_record(
    store: LocalTriggerStore,
    delivery: TriggerDelivery,
    *,
    status: str,
    trigger: LocalTrigger | None = None,
    error: str | None = None,
    response: str | None = None,
) -> None:
    try:
        await shield_and_drain(
            asyncio.to_thread(
                store.write_delivery_run_record,
                delivery,
                trigger=trigger,
                status=status,
                error=error,
                response=response,
            )
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
