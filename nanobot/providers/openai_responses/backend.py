"""Responses request construction, transport dispatch, and replay state ownership."""

from __future__ import annotations

import asyncio
import ssl
from collections import OrderedDict
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import httpx
from loguru import logger

from nanobot.providers.base import (
    LLMResponse,
    ProviderConversationState,
    resolve_stream_idle_timeout_s,
)
from nanobot.providers.openai_responses.compaction import (
    retained_compaction_messages,
    split_compaction_input,
)
from nanobot.providers.openai_responses.converters import convert_tools
from nanobot.providers.openai_responses.parsing import (
    ResponsesStreamCapture,
    consume_responses_events,
    iter_sdk_events,
    iter_sse,
    parse_response_output,
)
from nanobot.providers.openai_responses.state import (
    attach_responses_state,
    build_responses_compaction_state,
    is_compaction_compatibility_error,
    prepare_responses_input,
    resolve_compact_threshold,
    responses_state_context_tokens,
    responses_state_items,
)

if TYPE_CHECKING:
    from nanobot.providers.openai_responses.websocket import ResponsesWebSocketSession


@dataclass(frozen=True, slots=True)
class ResponsesWebSocketOptions:
    """Endpoint-specific handshake options and provider-wide resource limits."""

    beta_header: str | None = None
    max_sessions: int = 32


@dataclass(slots=True)
class PreparedResponsesRequest:
    body: dict[str, Any]
    replayed: bool


class ResponsesBackend:
    """Share protocol behavior while adapters supply authentication and capabilities."""

    def __init__(self, *, websocket_options: ResponsesWebSocketOptions | None = None) -> None:
        self.native_compaction_available = True
        self.websocket_options = websocket_options
        self._sessions: OrderedDict[str, ResponsesWebSocketSession] = OrderedDict()
        self._sessions_lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Release transports after the owning provider's requests have stopped."""
        sessions = list(self._sessions.values())
        self._sessions.clear()
        await asyncio.gather(*(session.aclose() for session in sessions))

    async def websocket_request(
        self,
        session_id: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        *,
        provider: str,
        verify: ssl.SSLContext,
        proxy: str | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse | None:
        from nanobot.providers.openai_responses.websocket import ResponsesWebSocketSession

        options = self.websocket_options
        if options is None:
            return None
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session is None:
                if len(self._sessions) >= options.max_sessions:
                    idle_id = next((
                        key for key, value in self._sessions.items() if value.active_requests == 0
                    ), None)
                    if idle_id is None:
                        return None
                    await self._sessions.pop(idle_id).aclose()
                session = ResponsesWebSocketSession(beta_header=options.beta_header)
                self._sessions[session_id] = session
            self._sessions.move_to_end(session_id)
            # Reserve before dropping the pool lock, including requests queued on this session.
            session.active_requests += 1
        try:
            return await session.request(
                url, headers, body, provider=provider, verify=verify, proxy=proxy,
                on_content_delta=on_content_delta, on_thinking_delta=on_thinking_delta,
                on_tool_call_delta=on_tool_call_delta,
            )
        finally:
            session.active_requests -= 1

    def prepare(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: str,
        model: str,
        state: ProviderConversationState | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        preserve_reasoning: bool = False,
    ) -> PreparedResponsesRequest:
        instructions, items, replayed = prepare_responses_input(
            messages, state=state, provider=provider, model=model,
            preserve_reasoning=preserve_reasoning,
        )
        body: dict[str, Any] = {
            "model": model,
            "instructions": instructions or None,
            "input": items,
            "store": False,
            "stream": False,
        }
        if tools:
            body["tools"] = convert_tools(tools)
            body["tool_choice"] = tool_choice or "auto"
        return PreparedResponsesRequest(body, replayed)

    def add_compaction(
        self, body: dict[str, Any], context_window_tokens: int | None, max_output_tokens: int,
    ) -> None:
        threshold = resolve_compact_threshold(context_window_tokens, max_output_tokens)
        if self.native_compaction_available and threshold is not None:
            body["context_management"] = [{"type": "compaction", "compact_threshold": threshold}]

    async def compact_before_request(
        self,
        body: dict[str, Any],
        *,
        provider: str,
        model: str,
        state: ProviderConversationState,
        context_window_tokens: int | None,
        max_output_tokens: int,
        input_budget: int | None,
        send: Callable[[dict[str, Any]], Awaitable[LLMResponse]],
    ) -> ProviderConversationState | None:
        """Compact prior history with a trigger while keeping pending tool pairs intact."""
        threshold = resolve_compact_threshold(context_window_tokens, max_output_tokens)
        if input_budget is None and (
            threshold is None or responses_state_context_tokens(state) < threshold
        ):
            return None
        history = responses_state_items(state) or []
        items = cast(list[dict[str, Any]], body["input"])
        history, delta = split_compaction_input(history, items[len(history):])
        try:
            compacted = await send({**body, "input": [*history, {"type": "compaction_trigger"}]})
            compact_items = (
                responses_state_items(compacted.provider_state)
                if compacted.provider_state is not None else None
            )
            if not compact_items or compact_items[-1].get("type") not in {
                "compaction", "compaction_summary", "context_compaction",
            }:
                raise RuntimeError("Responses compaction returned no compaction item")
            body["input"] = [*retained_compaction_messages(history), *compact_items, *delta]
            return build_responses_compaction_state(
                provider=provider, model=model, output_items=compact_items,
            )
        except Exception as exc:
            if is_compaction_compatibility_error(exc):
                self.native_compaction_available = False
            if input_budget is not None:
                # Required compaction cannot fall through to the original oversized request.
                raise
            logger.warning(
                "Responses trigger compaction unavailable; continuing without it "
                "(type={} status={} disabled={})",
                type(exc).__name__, getattr(exc, "status_code", None),
                not self.native_compaction_available,
            )
            return None

    @staticmethod
    async def consume(
        events: AsyncIterable[dict[str, Any]],
        *,
        provider: str | None = None,
        body: dict[str, Any] | None = None,
        capture: ResponsesStreamCapture | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_response_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        capture = capture if capture is not None else ResponsesStreamCapture()
        content, tools, finish, usage, reasoning = await consume_responses_events(
            events, on_content_delta=on_content_delta, on_tool_call_delta=on_tool_call_delta,
            on_reasoning_delta=on_thinking_delta, on_response_event=on_response_event,
            capture=capture,
        )
        result = LLMResponse(
            content=content, tool_calls=tools, finish_reason=finish,
            usage=usage, reasoning_content=reasoning,
        )
        if capture.completed and provider is not None and body is not None:
            attach_responses_state(
                result, provider=provider, model=str(body.get("model") or ""),
                input_items=cast(list[dict[str, Any]], body.get("input") or []),
                output_items=capture.output_items,
            )
        return result

    @staticmethod
    async def sse_request(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        *,
        error_factory: Callable[[int, httpx.Headers, str], Exception],
        provider: str | None = None,
        verify: ssl.SSLContext | bool | None = None,
        proxy: str | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_response_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        options: dict[str, Any] = {"timeout": resolve_stream_idle_timeout_s()}
        if verify is not None:
            options["verify"] = verify
        if proxy:
            options.update(proxy=proxy, trust_env=False)
        async with httpx.AsyncClient(**options) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    raw = (await response.aread()).decode("utf-8", "ignore")
                    raise error_factory(response.status_code, response.headers, raw)
                return await ResponsesBackend.consume(
                    iter_sse(response), provider=provider, body=body,
                    on_content_delta=on_content_delta, on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta, on_response_event=on_response_event,
                )

    async def sdk_request(
        self,
        client: Any,
        body: dict[str, Any],
        *,
        provider: str,
        extra_headers: dict[str, str] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        options: dict[str, Any] = {}
        if extra_headers is not None:
            options["extra_headers"] = extra_headers
        idle_timeout = resolve_stream_idle_timeout_s()
        if body.get("stream"):
            options["timeout"] = idle_timeout
        try:
            response = await client.responses.create(**body, **options)
        except Exception as exc:
            if "context_management" not in body or not is_compaction_compatibility_error(exc):
                raise
            self.native_compaction_available = False
            body.pop("context_management")
            logger.warning(
                "Responses server compaction unsupported; disabled for {} (status={})",
                provider, getattr(exc, "status_code", None),
            )
            response = await client.responses.create(**body, **options)
        if not body.get("stream"):
            return parse_response_output(
                response, state_provider=provider, state_model=str(body["model"]),
                state_input_items=cast(list[dict[str, Any]], body["input"]),
            )

        async def timed_events() -> AsyncIterable[dict[str, Any]]:
            events = iter_sdk_events(response).__aiter__()
            while True:
                try:
                    yield await asyncio.wait_for(anext(events), idle_timeout)
                except StopAsyncIteration:
                    return

        async with response:
            result = await self.consume(
                timed_events(), provider=provider, body=body,
                on_content_delta=on_content_delta, on_thinking_delta=on_thinking_delta,
                on_tool_call_delta=on_tool_call_delta,
            )
        result.content = result.content or None
        return result
