"""Agent hook that adapts runner events into channel progress UI."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.bus.outbound_events import ProgressEvent, StreamDeltaEvent, StreamEndEvent
from nanobot.events import NO_EVENTS, EventSink
from nanobot.providers.base import ToolCallRequest
from nanobot.utils.helpers import IncrementalThinkExtractor, strip_think
from nanobot.utils.progress_events import (
    build_tool_event_finish_payloads,
    build_tool_event_start_payload,
)
from nanobot.utils.tool_hints import format_tool_hints


class AgentProgressHook(AgentHook):
    """Translate runner lifecycle events into user-visible progress signals."""

    def __init__(
        self,
        events: EventSink = NO_EVENTS,
        *,
        streaming: bool = False,
        session_key: str | None = None,
        tool_hint_max_length: int = 40,
    ) -> None:
        super().__init__(reraise=True)
        self._publish = events.publish
        self._streaming = streaming
        self._session_key = session_key
        self._tool_hint_max_length = tool_hint_max_length
        self._stream_buf = ""
        self._think_extractor = IncrementalThinkExtractor()
        self._reasoning_open = False

    def wants_streaming(self) -> bool:
        return self._streaming

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        if not text:
            return None
        return strip_think(text) or None

    def _tool_hint(self, tool_calls: list[Any]) -> str:
        return format_tool_hints(tool_calls, max_length=self._tool_hint_max_length)

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        prev_clean = strip_think(self._stream_buf)
        self._stream_buf += delta
        new_clean = strip_think(self._stream_buf)
        incremental = new_clean[len(prev_clean) :]

        if await self._think_extractor.feed(self._stream_buf, self.emit_reasoning):
            context.streamed_reasoning = True

        if incremental:
            # Answer text has started; close the reasoning segment so the UI can
            # lock the bubble before the answer renders below it.
            await self.emit_reasoning_end()
            if self._publish and self._streaming:
                await self._publish(StreamDeltaEvent(content=incremental))

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        await self.emit_reasoning_end()
        if self._publish and self._streaming:
            await self._publish(StreamEndEvent(
                resuming=resuming, merge_next=context.stream_continues_current_message,
            ))
        self._stream_buf = ""
        self._think_extractor.reset()

    async def before_iteration(self, context: AgentHookContext) -> None:
        logger.debug(
            "Starting agent loop iteration {} for session {}",
            context.iteration,
            self._session_key,
        )

    async def on_provider_tool_event(
        self,
        context: AgentHookContext,
        event: dict[str, Any],
    ) -> None:
        if not self._publish:
            return
        phase = event.get("phase")
        name = event.get("name")
        call_id = event.get("call_id")
        if (
            phase not in {"start", "end", "error"}
            or not isinstance(name, str)
            or not name
            or not call_id
        ):
            return
        arguments = event.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        payload: dict[str, Any] = {
            "version": 1,
            "phase": phase,
            "call_id": str(call_id),
            "name": name,
            "arguments": arguments,
            "result": event.get("result") if phase == "end" else None,
            "error": event.get("error") if phase == "error" else None,
            "files": [],
            "embeds": [],
        }
        if phase == "start":
            await self.emit_reasoning_end()
            tool_call = ToolCallRequest(id=str(call_id), name=name, arguments=arguments)
            tool_hint = self._strip_think(self._tool_hint([tool_call])) or name
            await self._publish(ProgressEvent(
                content=tool_hint, tool_hint=True, tool_events=[payload],
            ))
            logger.info(
                "Provider-hosted tool call: {}({})",
                name,
                json.dumps(arguments, ensure_ascii=False)[:200],
            )
            return
        await self._publish(ProgressEvent(tool_events=[payload]))

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        if self._publish:
            if not self._streaming and not context.streamed_content:
                thought = self._strip_think(context.response.content if context.response else None)
                if thought:
                    await self._publish(ProgressEvent(content=thought))
            tool_hint = self._strip_think(self._tool_hint(context.tool_calls))
            tool_events = [build_tool_event_start_payload(tc) for tc in context.tool_calls]
            await self._publish(ProgressEvent(
                content=tool_hint or "", tool_hint=True, tool_events=tool_events,
            ))
        for tc in context.tool_calls:
            args_str = json.dumps(tc.arguments, ensure_ascii=False)
            logger.info("Tool call: {}({})", tc.name, args_str[:200])

    async def emit_reasoning(self, reasoning_content: str | None) -> None:
        """Publish a reasoning chunk; channel plugins decide whether to render."""
        if self._publish and reasoning_content:
            self._reasoning_open = True
            await self._publish(ProgressEvent(content=reasoning_content, reasoning_delta=True))

    async def emit_reasoning_end(self) -> None:
        """Close the current reasoning stream segment, if any was open."""
        if self._reasoning_open and self._publish:
            self._reasoning_open = False
            await self._publish(ProgressEvent(reasoning_end=True))
        else:
            self._reasoning_open = False

    async def after_iteration(self, context: AgentHookContext) -> None:
        if (
            self._publish
            and context.tool_calls
            and context.tool_events
        ):
            tool_events = build_tool_event_finish_payloads(context)
            if tool_events:
                await self._publish(ProgressEvent(tool_events=tool_events))
        u = context.usage
        logger.debug(
            "LLM usage: input={} output={} cache_read={} cache_write={} source={}",
            u.input_tokens if u else 0,
            u.output_tokens if u else 0,
            u.cache_read_tokens if u else None,
            u.cache_write_tokens if u else None,
            u.source if u else "missing",
        )

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        return self._strip_think(content)
