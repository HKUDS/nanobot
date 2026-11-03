from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Literal
from uuid import uuid4

from nanobot.events import CompactionReason, ContextCompactionEvent, EventSink
from nanobot.utils.cancellation import shield_and_drain


class ProviderCompactionEvents:
    """Keep one compaction pending across attempts in a provider retry chain."""

    def __init__(self, events: EventSink) -> None:
        self._events = events
        self._active: ContextCompactionEvent | None = None

    async def start(self, reason: CompactionReason) -> str:
        if self._active is None:
            self._active = ContextCompactionEvent(uuid4().hex, "started", reason=reason)
            await self._events.emit(self._active)
        return self._active.compaction_id

    async def finish(self, phase: Literal["succeeded", "failed", "cancelled"]) -> None:
        if self._active is None:
            return
        event = replace(self._active, phase=phase)
        self._active = None
        await shield_and_drain(self._events.emit(event))


@asynccontextmanager
async def provider_compaction_scope(
    events: EventSink,
    existing: ProviderCompactionEvents | None = None,
) -> AsyncGenerator[ProviderCompactionEvents]:
    if existing is not None:
        yield existing
        return
    compaction = ProviderCompactionEvents(events)
    try:
        yield compaction
    except asyncio.CancelledError:
        await compaction.finish("cancelled")
        raise
    finally:
        await compaction.finish("failed")
