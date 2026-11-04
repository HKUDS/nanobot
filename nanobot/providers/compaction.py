from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from nanobot.events import CompactionReason, ContextCompactionEvent, EventSink
from nanobot.utils.cancellation import shield_and_drain

if TYPE_CHECKING:
    from nanobot.providers.base import ProviderConversationState


@dataclass(frozen=True)
class NativeCompaction:
    """Accepted continuation and its distinct, summary-only archive input."""

    state: ProviderConversationState
    summary_state: ProviderConversationState
    event_id: str


class ProviderStateCommitError(RuntimeError):
    """A local continuation commit failed; provider retry/failover cannot repair it."""


class ProviderCompactionEvents:
    """Own pending and accepted compaction across one provider retry chain."""

    def __init__(self, events: EventSink) -> None:
        self._events = events
        self._active: ContextCompactionEvent | None = None
        self.accepted: NativeCompaction | None = None

    async def accept(
        self,
        receipt: NativeCompaction,
        commit: Callable[[ProviderConversationState], Awaitable[None]] | None,
    ) -> None:
        """Settle valid native output before generation, even when the caller stops."""
        async def settle() -> None:
            try:
                if commit is not None:
                    await commit(receipt.state)
                self.accepted = receipt
            except Exception as exc:
                raise ProviderStateCommitError("Could not save compacted provider state") from exc
            finally:
                # Native compaction succeeded even if the local checkpoint failed.
                await self.finish("succeeded")

        await shield_and_drain(settle())

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
