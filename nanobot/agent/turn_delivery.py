"""Route and publish the user-visible lifecycle of an agent turn."""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import (
    RetryWaitEvent,
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
    outbound_message_for_event,
)
from nanobot.bus.progress import build_bus_progress_callback
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventBus, RuntimeEventPublisher


@dataclass(frozen=True)
class TurnRoute:
    """Turn delivery destination and lifecycle policy, separate from execution input."""

    channel: str
    chat_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    publish_lifecycle: bool = False


TurnRoutePolicy = Callable[[InboundMessage, str, TurnRoute], TurnRoute]
ProgressCallback = Callable[..., Awaitable[None]]
StreamCallback = Callable[[str], Awaitable[None]]
StreamEndCallback = Callable[..., Awaitable[None]]
RetryWaitCallback = Callable[[str], Awaitable[None]]


class TurnDeliveryFactory:
    """Create per-turn delivery objects from an optional edge-owned route policy."""

    def __init__(
        self,
        bus: MessageBus,
        runtime_events: RuntimeEventBus,
        route_policy: TurnRoutePolicy | None = None,
    ) -> None:
        self.bus = bus
        self.runtime_events = runtime_events
        self.runtime_event_publisher = RuntimeEventPublisher(runtime_events)
        self.route_policy = route_policy

    def create(
        self,
        msg: InboundMessage,
        session_key: str,
        *,
        enable_stream: bool = False,
    ) -> TurnDelivery:
        route = self._default_route(msg, session_key)
        if self.route_policy is not None:
            route = self.route_policy(msg, session_key, route)
            if not isinstance(route, TurnRoute):
                raise TypeError("turn route policy must return TurnRoute")
        return TurnDelivery(
            bus=self.bus,
            runtime_event_publisher=self.runtime_event_publisher,
            input_message=msg,
            session_key=session_key,
            route=route,
            enable_stream=enable_stream,
        )

    def unrouted(self, msg: InboundMessage, session_key: str) -> TurnDelivery:
        """Create a lifecycle fallback without invoking edge routing policy."""
        return TurnDelivery(
            bus=self.bus,
            runtime_event_publisher=self.runtime_event_publisher,
            input_message=msg,
            session_key=session_key,
            route=TurnRoute(
                channel=msg.channel,
                chat_id=msg.chat_id,
                metadata=dict(msg.metadata or {}),
            ),
        )

    @staticmethod
    def _default_route(msg: InboundMessage, session_key: str) -> TurnRoute:
        if msg.channel != "system":
            return TurnRoute(
                channel=msg.channel,
                chat_id=msg.chat_id,
                metadata=dict(msg.metadata or {}),
                publish_lifecycle=True,
            )

        channel, chat_id = (
            msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
        )
        metadata: dict[str, Any] = {}
        if (
            channel == "slack"
            and session_key.startswith("slack:")
            and session_key.count(":") >= 2
        ):
            metadata["slack"] = {"thread_ts": session_key.split(":", 2)[2]}
        if origin_message_id := msg.metadata.get("origin_message_id"):
            metadata["origin_message_id"] = origin_message_id
        return TurnRoute(channel=channel, chat_id=chat_id, metadata=metadata)


@dataclass
class TurnDelivery:
    """Own routing, callbacks, and lifecycle publication for one turn."""

    bus: MessageBus
    runtime_event_publisher: RuntimeEventPublisher
    input_message: InboundMessage
    session_key: str
    route: TurnRoute
    enable_stream: bool = False
    delivery_message: InboundMessage = field(init=False)
    lifecycle_message: InboundMessage = field(init=False)
    _stream_base_id: str | None = field(init=False, default=None)
    _stream_segment: int = field(init=False, default=0)
    _stream_open: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.delivery_message = dataclasses.replace(
            self.input_message,
            channel=self.route.channel,
            chat_id=self.route.chat_id,
            metadata=dict(self.route.metadata),
        )
        self.lifecycle_message = (
            self.delivery_message if self.route.publish_lifecycle else self.input_message
        )
        if self.enable_stream and self.delivery_message.metadata.get("_wants_stream"):
            self._stream_base_id = f"{self.session_key}:{time.time_ns()}"

    @property
    def on_stream(self) -> StreamCallback | None:
        return self._publish_stream if self._stream_base_id is not None else None

    @property
    def on_stream_end(self) -> StreamEndCallback | None:
        return self._publish_stream_end if self._stream_base_id is not None else None

    def progress_callback(self) -> ProgressCallback | None:
        if not self.route.publish_lifecycle:
            return None
        return build_bus_progress_callback(self.bus, self.delivery_message)

    def retry_wait_callback(self) -> RetryWaitCallback | None:
        if not self.route.publish_lifecycle:
            return None

        async def _on_retry_wait(content: str) -> None:
            await self.bus.publish_outbound(
                outbound_message_for_event(
                    channel=self.delivery_message.channel,
                    chat_id=self.delivery_message.chat_id,
                    event=RetryWaitEvent(content=content),
                    metadata=self.delivery_message.metadata,
                )
            )

        return _on_retry_wait

    async def started(self) -> None:
        if self.route.publish_lifecycle:
            await self.runtime_event_publisher.session_turn_started(
                self.delivery_message,
                self.session_key,
            )

    async def running(self, *, started_at: float) -> None:
        if self.route.publish_lifecycle:
            await self.runtime_event_publisher.run_status_changed(
                self.delivery_message,
                self.session_key,
                "running",
                started_at=started_at,
            )

    def record_runtime(self, runtime: Any) -> None:
        self.runtime_event_publisher.record_turn_runtime(self.session_key, runtime)

    def record_latency(self, latency_ms: int | None) -> None:
        self.runtime_event_publisher.record_turn_latency(self.session_key, latency_ms)

    def background_response(
        self,
        content: str | None,
        *,
        stop_reason: str,
        streamed: bool,
        latency_ms: int | None,
    ) -> OutboundMessage:
        metadata = dict(self.route.metadata)
        if self.route.publish_lifecycle and latency_ms is not None:
            metadata["latency_ms"] = int(latency_ms)
        event = (
            StreamedResponseEvent()
            if self.route.publish_lifecycle
            and streamed
            and stop_reason not in {"error", "tool_error"}
            else None
        )
        return OutboundMessage(
            channel=self.route.channel,
            chat_id=self.route.chat_id,
            content=content or "Background task completed.",
            metadata=metadata,
            event=event,
        )

    async def complete(
        self,
        response: OutboundMessage | None,
        *,
        publish_completion: bool,
    ) -> None:
        completed_channel = self.lifecycle_message.channel
        completed_chat_id = self.lifecycle_message.chat_id
        if response is not None:
            await self.bus.publish_outbound(response)
            completed_channel = response.channel
            completed_chat_id = response.chat_id
        elif self.lifecycle_message.channel == "cli":
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=self.lifecycle_message.channel,
                    chat_id=self.lifecycle_message.chat_id,
                    content="",
                    metadata=dict(self.lifecycle_message.metadata or {}),
                )
            )
        if publish_completion:
            await self.runtime_event_publisher.turn_completed(
                channel=completed_channel,
                chat_id=completed_chat_id,
                session_key=self.session_key,
                metadata=self.lifecycle_message.metadata,
            )

    async def fail(self, *, publish_completion: bool) -> None:
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=self.lifecycle_message.channel,
                chat_id=self.lifecycle_message.chat_id,
                content="Sorry, I encountered an error.",
                metadata=dict(self.lifecycle_message.metadata or {}),
            )
        )
        if publish_completion:
            await self.runtime_event_publisher.turn_completed(
                channel=self.lifecycle_message.channel,
                chat_id=self.lifecycle_message.chat_id,
                session_key=self.session_key,
                metadata=self.lifecycle_message.metadata,
            )

    async def idle(self) -> None:
        await self.runtime_event_publisher.run_status_changed(
            self.lifecycle_message,
            self.session_key,
            "idle",
        )
        self.runtime_event_publisher.clear_turn(self.session_key)

    def _stream_id(self) -> str:
        assert self._stream_base_id is not None
        return f"{self._stream_base_id}:{self._stream_segment}"

    async def _publish_stream(self, delta: str) -> None:
        await self.bus.publish_outbound(
            outbound_message_for_event(
                channel=self.delivery_message.channel,
                chat_id=self.delivery_message.chat_id,
                event=StreamDeltaEvent(content=delta, stream_id=self._stream_id()),
                metadata=self.delivery_message.metadata,
            )
        )
        self._stream_open = True

    async def _publish_stream_end(
        self,
        *,
        resuming: bool = False,
        merge_next: bool = False,
    ) -> None:
        await self.bus.publish_outbound(
            outbound_message_for_event(
                channel=self.delivery_message.channel,
                chat_id=self.delivery_message.chat_id,
                event=StreamEndEvent(
                    stream_id=self._stream_id(),
                    resuming=resuming,
                    merge_next=merge_next,
                ),
                metadata=self.delivery_message.metadata,
            )
        )
        self._stream_open = merge_next
        if not merge_next:
            self._stream_segment += 1

    async def abort_stream(self) -> None:
        """Close an interrupted stream so stateful channels can release its buffer."""
        if self._stream_open:
            await self._publish_stream_end()
