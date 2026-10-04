"""Queued delivery of messages and typed events between core and channels."""

import asyncio
import contextlib
import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar, overload

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import outbound_message_for_event
from nanobot.events import AgentEvent

_EventT = TypeVar("_EventT", bound=AgentEvent)
EventHandler = Callable[[AgentEvent], Awaitable[None] | None]


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue. Core operations publish text,
    media, or typed events to the same routed outbound queue, independently of
    whether an LLM produced them. Channel adapters own their wire projection.

    Local subscribers are awaited by ``publish``; channel delivery is queued by
    ``publish_event``. Local state transitions never wait for network sends.
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._handlers: list[EventHandler] = []
        self._pending: set[asyncio.Task[None]] = set()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Queue a routed message or event for its channel."""
        await self.outbound.put(msg)

    async def publish_event(
        self,
        event: AgentEvent,
        *,
        channel: str,
        chat_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue a typed event using the existing outbound delivery contract.

        The bus transports event values without inspecting their fields. Known
        events retain their text fallback; channel adapters decide how to render
        or ignore events they receive.
        """
        await self.publish_outbound(outbound_message_for_event(
            channel=channel, chat_id=chat_id, event=event, metadata=metadata,
        ))

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()

    @overload
    def subscribe(
        self, handler: Callable[[_EventT], Awaitable[None] | None],
        event_type: type[_EventT],
    ) -> Callable[[], None]: ...

    @overload
    def subscribe(
        self, handler: EventHandler, event_type: None = None,
    ) -> Callable[[], None]: ...

    def subscribe(
        self,
        handler: Callable[..., Awaitable[None] | None],
        event_type: type[AgentEvent] | None = None,
    ) -> Callable[[], None]:
        """Connect an ordered, awaited handler; return its idempotent disconnect.

        The overloads bind handler and event type. The erased callable exists
        only at this heterogeneous dispatch boundary, behind the type filter.
        """
        active = True

        def entry(event: AgentEvent) -> Awaitable[None] | None:
            if active and (event_type is None or isinstance(event, event_type)):
                return handler(event)
            return None
        self._handlers.append(entry)

        def _unsubscribe() -> None:
            nonlocal active
            active = False
            with contextlib.suppress(ValueError):
                self._handlers.remove(entry)

        return _unsubscribe

    async def publish(self, event: AgentEvent) -> None:
        """Await local subscribers in registration order, without channel delivery."""
        for handler in list(self._handlers):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("event handler failed for {}", type(event).__name__)

    def publish_nowait(self, event: AgentEvent) -> asyncio.Task[None] | None:
        """Schedule local dispatch, retaining it until completion.

        Unlike ``publish``, the caller does not wait for handlers. This does not
        turn individual handlers into independent workers or change their order.
        Separate publications may interleave; this is not a global event FIFO.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("dropping event without a running loop: {}", type(event).__name__)
            return None
        task = loop.create_task(self.publish(event))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task

    async def drain(self) -> None:
        """Finish scheduled dispatches after producers stop, before disconnecting."""
        while self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
