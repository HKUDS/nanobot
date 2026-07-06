"""Streaming support for the high-level Python SDK."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from copy import deepcopy

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.sdk.types import (
    STREAM_EVENT_REASONING_COMPLETED,
    STREAM_EVENT_REASONING_DELTA,
    STREAM_EVENT_TEXT_COMPLETED,
    STREAM_EVENT_TEXT_DELTA,
    STREAM_EVENT_TOOL_COMPLETED,
    STREAM_EVENT_TOOL_FAILED,
    STREAM_EVENT_TOOL_STARTED,
    RunResult,
    StreamEvent,
)

_STREAM_SENTINEL = object()


class RunStream:
    """A running SDK turn with Cursor/OpenAI-style event streaming."""

    def __init__(
        self,
        task: asyncio.Task[RunResult],
        queue: asyncio.Queue[StreamEvent | object],
    ) -> None:
        self._task = task
        self._queue = queue
        self._events_started = False
        self._events_done = False
        self._stream_active = False
        self._closed = False

    @property
    def done(self) -> bool:
        """Whether the underlying run task has finished."""
        return self._task.done()

    async def stream_events(self) -> AsyncIterator[StreamEvent]:
        """Yield streaming events for this run.

        The event stream is single-consumer: call this method only once. Closing
        the iterator before completion cancels the underlying run.
        """
        if self._events_started:
            raise RuntimeError("RunStream.stream_events() can only be consumed once")
        self._events_started = True
        self._stream_active = True
        try:
            while True:
                item = await self._queue.get()
                if item is _STREAM_SENTINEL:
                    self._events_done = True
                    break
                yield item
        finally:
            self._stream_active = False
            if not self._events_done:
                await self.aclose()

    async def wait(self) -> RunResult:
        """Wait for the run to finish and return its final result."""
        if not self._events_done and not self._stream_active:
            if not self._events_started:
                self._events_started = True
            await self._drain_events()
        return await self._task

    async def text(self) -> str:
        """Wait for the run to finish and return the final text."""
        return (await self.wait()).content

    async def cancel(self) -> None:
        """Cancel the running turn and release stream resources."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the stream, cancelling the run if it is still active."""
        if self._closed:
            return
        self._closed = True
        if not self._task.done():
            self._task.cancel()
        self._finish_events()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            # Closing is cleanup; wait() remains the API that surfaces run errors.
            pass

    async def _drain_events(self) -> None:
        while not self._events_done:
            item = await self._queue.get()
            if item is _STREAM_SENTINEL:
                self._events_done = True
                break

    def _finish_events(self) -> None:
        self._events_done = True
        while True:
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                continue
            break
        with suppress(asyncio.QueueFull):
            self._queue.put_nowait(_STREAM_SENTINEL)


class SDKStreamEmitter:
    """Serialize SDK streaming events onto a bounded async queue."""

    def __init__(self, queue: asyncio.Queue[StreamEvent | object]) -> None:
        self._queue = queue
        self._text_parts: list[str] = []
        self._closed = False

    async def emit(self, event: StreamEvent) -> None:
        if self._closed:
            return
        await self._queue.put(event)

    async def text_delta(self, delta: str, *, iteration: int | None = None) -> None:
        if not delta:
            return
        self._text_parts.append(delta)
        await self.emit(StreamEvent(
            type=STREAM_EVENT_TEXT_DELTA,
            delta=delta,
            iteration=iteration,
        ))

    async def text_completed(
        self,
        *,
        resuming: bool = False,
        iteration: int | None = None,
        force: bool = True,
    ) -> None:
        content = "".join(self._text_parts)
        if not content and (resuming or not force):
            return
        self._text_parts = []
        await self.emit(StreamEvent(
            type=STREAM_EVENT_TEXT_COMPLETED,
            content=content,
            iteration=iteration,
            resuming=resuming,
        ))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._queue.full():
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        with suppress(asyncio.QueueFull):
            self._queue.put_nowait(_STREAM_SENTINEL)


class SDKStreamingHook(AgentHook):
    """Convert agent lifecycle hooks into public SDK stream events."""

    def __init__(self, emitter: SDKStreamEmitter) -> None:
        super().__init__()
        self._emitter = emitter
        self._reasoning_open = False

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for call in context.tool_calls:
            await self._emitter.emit(StreamEvent(
                type=STREAM_EVENT_TOOL_STARTED,
                name=call.name,
                tool_call_id=call.id,
                arguments=deepcopy(call.arguments),
                iteration=context.iteration,
            ))

    async def emit_reasoning(self, reasoning_content: str | None) -> None:
        if not reasoning_content:
            return
        self._reasoning_open = True
        await self._emitter.emit(StreamEvent(
            type=STREAM_EVENT_REASONING_DELTA,
            delta=reasoning_content,
        ))

    async def emit_reasoning_end(self) -> None:
        if not self._reasoning_open:
            return
        self._reasoning_open = False
        await self._emitter.emit(StreamEvent(type=STREAM_EVENT_REASONING_COMPLETED))

    async def after_iteration(self, context: AgentHookContext) -> None:
        if not context.tool_events:
            return
        for index, raw_event in enumerate(context.tool_events):
            call = context.tool_calls[index] if index < len(context.tool_calls) else None
            event = dict(raw_event)
            status = event.get("status")
            name = str(event.get("name") or (call.name if call else ""))
            event_type = (
                STREAM_EVENT_TOOL_COMPLETED if status == "ok" else STREAM_EVENT_TOOL_FAILED
            )
            await self._emitter.emit(StreamEvent(
                type=event_type,
                name=name or None,
                tool_call_id=call.id if call else None,
                arguments=deepcopy(call.arguments) if call else None,
                iteration=context.iteration,
                error=None if status == "ok" else str(event.get("detail") or ""),
                metadata=event,
            ))
