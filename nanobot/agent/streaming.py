"""Streaming response callbacks for bus-backed channels."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


@dataclass(frozen=True)
class StreamCallbacks:
    on_stream: Callable[[str], Awaitable[None]]
    on_stream_end: Callable[..., Awaitable[None]]


class StreamingCoordinator:
    """Builds outbound bus callbacks for segmented response streaming."""

    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus

    def build_callbacks(self, msg: InboundMessage) -> StreamCallbacks:
        """Split one answer into stream segments and publish deltas to the bus."""
        stream_base_id = f"{msg.session_key}:{time.time_ns()}"
        stream_segment = 0

        def _current_stream_id() -> str:
            return f"{stream_base_id}:{stream_segment}"

        async def on_stream(delta: str) -> None:
            meta = dict(msg.metadata or {})
            meta["_stream_delta"] = True
            meta["_stream_id"] = _current_stream_id()
            await self._bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=delta,
                    metadata=meta,
                )
            )

        async def on_stream_end(*, resuming: bool = False) -> None:
            nonlocal stream_segment
            meta = dict(msg.metadata or {})
            meta["_stream_end"] = True
            meta["_resuming"] = resuming
            meta["_stream_id"] = _current_stream_id()
            await self._bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="",
                    metadata=meta,
                )
            )
            stream_segment += 1

        return StreamCallbacks(on_stream=on_stream, on_stream_end=on_stream_end)
