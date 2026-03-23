"""Factory for bus-backed progress callbacks.

Provides :func:`make_bus_progress`, a standalone factory that builds a
:data:`~nanobot.agent.callbacks.ProgressCallback` publishing structured
progress events onto the message bus as :class:`OutboundMessage` objects.

Extracted from :meth:`AgentLoop._make_bus_progress` to reduce the surface
area of ``loop.py`` and allow independent testing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    ProgressCallback,
    ProgressEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)
from nanobot.bus.events import OutboundMessage

if TYPE_CHECKING:
    from nanobot.bus.canonical import CanonicalEventBuilder
    from nanobot.bus.queue import MessageBus


def make_bus_progress(
    *,
    bus: MessageBus,
    channel: str,
    chat_id: str,
    base_meta: dict,
    canonical_builder: CanonicalEventBuilder,
) -> ProgressCallback:
    """Return a ``ProgressCallback`` that publishes structured progress events onto the bus.

    Each call shallow-copies ``base_meta``, merges per-event fields, and
    attaches the appropriate canonical event from ``canonical_builder``
    before publishing an ``OutboundMessage`` with ``_progress=True``.

    The returned coroutine captures ``channel``, ``chat_id``, ``base_meta``,
    and ``canonical_builder`` by value so it remains valid for the full turn
    even if the caller rebinds its local variables.
    """

    async def _progress(event: ProgressEvent) -> None:
        meta = dict(base_meta)  # inherits _progress=True from base_meta
        match event:
            case TextChunk(content=content, streaming=streaming):
                meta["_streaming"] = streaming
                if content:
                    meta["_canonical"] = canonical_builder.text_flush(content)
            case ToolCallEvent(tool_call_id=tcid, tool_name=name, args=args):
                meta["_tool_hint"] = True  # preserved for ChannelManager gate
                meta["_tool_call"] = {"toolCallId": tcid, "toolName": name, "args": args}
                meta["_canonical"] = canonical_builder.tool_call(
                    tool_call_id=tcid, tool_name=name, args=args
                )
            case ToolResultEvent(tool_call_id=tcid, result=result, tool_name=name):
                meta["_tool_result"] = {"toolCallId": tcid, "result": result}
                meta["_canonical"] = canonical_builder.tool_result(
                    tool_call_id=tcid, tool_name=name, result=result
                )
            case DelegateStartEvent(delegation_id=did, child_role=role, task_title=title):
                meta["_canonical"] = canonical_builder.delegate_start(
                    delegation_id=did, child_role=role, task_title=title
                )
            case DelegateEndEvent(delegation_id=did, success=success):
                meta["_canonical"] = canonical_builder.delegate_end(
                    delegation_id=did, success=success
                )
            case StatusEvent(status_code=code, label=label):
                meta["_canonical"] = canonical_builder.status(code, label=label)
        await bus.publish_outbound(
            OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=event.content if isinstance(event, TextChunk) else "",
                metadata=meta,
            )
        )

    return _progress


__all__ = ["make_bus_progress"]
