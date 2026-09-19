"""Route and publish the user-visible lifecycle of an agent turn."""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.notification_delivery import notification_is_deliverable
from nanobot.bus.outbound_events import (
    RetryStatusEvent,
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
)
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventPublisher
from nanobot.channels.notification_routes import notification_metadata
from nanobot.events import AgentEvent, EventSink
from nanobot.providers.base import LLMUsage
from nanobot.session.keys import UNIFIED_SESSION_KEY, last_channel_from_metadata

if TYPE_CHECKING:
    from nanobot.utils.llm_runtime import LLMRuntime


@dataclass(frozen=True)
class TurnRoute:
    """Turn delivery destination and lifecycle policy, separate from execution input."""

    channel: str
    chat_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    publish_lifecycle: bool = False


TurnRoutePolicy = Callable[[InboundMessage, str, TurnRoute], TurnRoute]


def _bind_events(
    bus: MessageBus, route: TurnRoute,
) -> EventSink:
    channel, chat_id = route.channel, route.chat_id
    metadata = deepcopy(route.metadata)

    def accepts(event_type: type[AgentEvent]) -> bool:
        return notification_is_deliverable(
            event_type, channel=channel, publish_lifecycle=route.publish_lifecycle,
        )

    async def publish(event: AgentEvent) -> None:
        if not accepts(type(event)):
            return
        await bus.publish_event(
            event, channel=channel, chat_id=chat_id, metadata=deepcopy(metadata),
        )

    return EventSink(publish, accepts)


def _turn_outcome(stop_reason: object) -> tuple[str, str | None]:
    if stop_reason == "error":
        return "failed", "model"
    if stop_reason == "tool_error":
        return "failed", "tool"
    return "completed", None


class TurnDeliveryFactory:
    """Route turn delivery and session-level notifications."""

    def __init__(
        self,
        bus: MessageBus,
        route_policy: TurnRoutePolicy | None = None,
    ) -> None:
        self.bus = bus
        self.runtime_event_publisher = RuntimeEventPublisher(bus)
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
            if not isinstance(cast(object, route), TurnRoute):
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

    def session_events(
        self,
        session_key: str,
        session_metadata: dict[str, Any],
    ) -> EventSink:
        """Bind idle notifications to one route without acquiring a turn owner."""
        saved_route = session_metadata.get("_compaction_route")
        if isinstance(saved_route, dict):
            saved_route = cast(dict[str, Any], saved_route)
            channel, chat_id = saved_route.get("channel"), saved_route.get("chat_id")
            metadata = saved_route.get("metadata", {})
            if not isinstance(channel, str) or not isinstance(chat_id, str):
                return EventSink()
            if not isinstance(metadata, dict):
                return EventSink()
            metadata = cast(dict[str, Any], metadata)
        else:
            # Older sessions have no route snapshot. Only direct clients have a
            # session key that is also an unambiguous delivery address.
            route = (
                last_channel_from_metadata(session_metadata)
                if session_key == UNIFIED_SESSION_KEY
                else tuple(session_key.split(":", 1))
            )
            if not route or len(route) != 2 or route[0] not in {"websocket", "cli"}:
                return EventSink()
            channel, chat_id = route
            metadata = {}
        metadata = deepcopy(metadata)

        return _bind_events(self.bus, TurnRoute(channel, chat_id, metadata))

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
    events: EventSink = field(init=False)
    _routed_events: EventSink = field(init=False)
    _stop_reason: str | None = field(init=False, default=None)
    _failure_error_kind: str | None = field(init=False, default=None)
    _retry_status: RetryStatusEvent | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._routed_events = _bind_events(self.bus, self.route)
        self.events = EventSink(self._publish_event, self._routed_events.accepts)
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
    def streaming(self) -> bool:
        return self._stream_base_id is not None

    def remember_session_route(self, session_metadata: dict[str, Any]) -> None:
        """Keep only routing fields needed to deliver a later idle notification."""
        # Keep the storage key readable by older gateways.
        session_metadata["_compaction_route"] = {
            "channel": self.route.channel,
            "chat_id": self.route.chat_id,
            "metadata": notification_metadata(self.route.channel, self.route.metadata),
        }

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

    async def runtime_admitted(self, runtime: LLMRuntime) -> None:
        """Record the immutable runtime and expose it at the lifecycle seam."""
        if self.route.publish_lifecycle:
            await self.runtime_event_publisher.turn_runtime_admitted(
                self.delivery_message,
                self.session_key,
                runtime,
            )
            return
        self.runtime_event_publisher.record_turn_runtime(self.session_key, runtime)

    def record_latency(self, latency_ms: int | None) -> None:
        self.runtime_event_publisher.record_turn_latency(self.session_key, latency_ms)

    def record_usage(self, round_usages: list[LLMUsage]) -> None:
        self.runtime_event_publisher.record_turn_usage(self.session_key, round_usages)

    def record_stop_reason(
        self,
        stop_reason: str,
        *,
        failure_error_kind: str | None = None,
    ) -> None:
        self._stop_reason = stop_reason
        self._failure_error_kind = failure_error_kind

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
        stop_reason = self._stop_reason
        if stop_reason is None and response is not None:
            stop_reason = cast(str | None, response.metadata.get("_stop_reason"))
        completed_channel = self.lifecycle_message.channel
        completed_chat_id = self.lifecycle_message.chat_id
        if response is not None:
            completed_channel = response.channel
            completed_chat_id = response.chat_id
            if response.channel != "websocket" or stop_reason != "error":
                await self.bus.publish_outbound(response)
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
            outcome, failure_kind = _turn_outcome(stop_reason)
            await self.runtime_event_publisher.turn_completed(
                channel=completed_channel,
                chat_id=completed_chat_id,
                session_key=self.session_key,
                metadata=self.lifecycle_message.metadata,
                outcome=outcome,
                failure_kind=failure_kind,
                failure_error_kind=(self._failure_error_kind or (
                    self._retry_status.error_kind if failure_kind == "model" and self._retry_status else None
                )),
                failure_attempts=(
                    self._retry_status.attempt if failure_kind == "model" and self._retry_status else None
                ),
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
                outcome="failed",
                failure_kind="internal",
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

    async def _publish_event(self, event: AgentEvent) -> None:
        if isinstance(event, RetryStatusEvent):
            self._retry_status = event if event.state == "exhausted" else None
        if isinstance(event, StreamDeltaEvent | StreamEndEvent):
            if not self.streaming:
                return
            event = dataclasses.replace(event, stream_id=self._stream_id())
        if self._routed_events.publish is not None:
            await self._routed_events.publish(event)
        if isinstance(event, StreamDeltaEvent):
            self._stream_open = True
        elif isinstance(event, StreamEndEvent):
            self._stream_open = event.merge_next
            if not event.merge_next:
                self._stream_segment += 1

    async def abort_stream(self) -> None:
        """Close an interrupted stream so stateful channels can release its buffer."""
        if self._stream_open:
            await self._publish_event(StreamEndEvent())
