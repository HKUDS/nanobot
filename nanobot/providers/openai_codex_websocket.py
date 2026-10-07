"""Connection-local continuation for Codex's Responses WebSocket protocol."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

from loguru import logger
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, ProxyError
from websockets.protocol import State

from nanobot.providers.base import LLMProvider, LLMResponse, resolve_stream_idle_timeout_s
from nanobot.providers.openai_responses import (
    ResponsesStreamCapture,
    build_responses_state,
    consume_responses_events,
    is_replayable_finish_reason,
)

_WEBSOCKET_BETA = "responses_websockets=2026-02-06"


def _fingerprint(value: object) -> bytes:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).digest()


def _input_fingerprint(items: list[dict[str, Any]]) -> bytes:
    # Response item IDs and reasoning status are stripped by HTTP history replay.
    return _fingerprint([
        {
            key: value for key, value in item.items()
            if key != "id" and not (key == "status" and item.get("type") == "reasoning")
        }
        for item in items
    ])


def _error_token(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.:/\[\]-]{1,160}", value):
        return value
    return None


class CodexWebSocketError(RuntimeError):
    """Bounded API error metadata without upstream prompt or credential echoes."""

    def __init__(self, event: dict[str, Any], status_code: int | None = None):
        response = event.get("response")
        payload = cast(dict[str, Any], response) if isinstance(response, dict) else event
        error = payload.get("error")
        fields = cast(dict[str, object], error) if isinstance(error, dict) else payload
        status = event.get("status", event.get("status_code", status_code))
        self.status_code = status if isinstance(status, int) and 400 <= status <= 599 else None
        self.error_type = _error_token(fields.get("type"))
        self.error_code = _error_token(fields.get("code"))
        self.error_param = _error_token(fields.get("param"))
        self.retry_after = None
        raw_headers = event.get("headers") or fields.get("headers")
        if isinstance(raw_headers, dict):
            self.retry_after = LLMProvider._extract_retry_after_from_headers(raw_headers)
        # Classify errors without retaining untrusted upstream messages.
        message = fields.get("message")
        error_response = LLMResponse(
            content=" ".join(value for value in (message, self.error_type, self.error_code) if isinstance(value, str)),
            finish_reason="error",
            error_status_code=self.status_code,
            error_type=self.error_type,
            error_code=self.error_code,
        )
        if self.status_code == 429:
            self.should_retry = LLMProvider._is_retryable_429_response(error_response)
        elif self.status_code is None:
            self.should_retry = LLMProvider.is_transient_response(error_response)
        else:
            self.should_retry = self.status_code in {408, 409} or self.status_code >= 500
        self.should_retry |= self.error_code in {"previous_response_not_found", "websocket_connection_limit_reached"}
        self.request_id = (
            _error_token(cast(dict[str, Any], raw_headers).get("x-request-id"))
            if isinstance(raw_headers, dict) else None
        )
        self.compaction_unsupported = self.status_code in {400, 404, 422} and any(
            marker in str(message).lower()
            for marker in ("context_management", "compact_threshold", "compaction_trigger")
        )
        super().__init__(
            f"HTTP {self.status_code}: Codex WebSocket request failed"
            if self.status_code is not None else "Codex WebSocket request failed"
        )


class CodexWebSocketSession:
    """Serialize requests and retain continuation only on their authenticated socket."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self._connection: ClientConnection | None = None
        self._auth_fingerprint: bytes | None = None
        self._properties_fingerprint: bytes | None = None
        self._prefix_fingerprint: bytes | None = None
        self._prefix_length = 0
        self._response_id: str | None = None
        self._http_only = False

    async def aclose(self) -> None:
        connection, self._connection = self._connection, None
        self._response_id = None
        self._prefix_fingerprint = None
        self._properties_fingerprint = None
        self._prefix_length = 0
        if connection is not None:
            await connection.close()

    async def request(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        *,
        verify: ssl.SSLContext,
        proxy: str | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse | None:
        """Return None when this session must use the HTTP transport."""
        async with self.lock:
            auth_fingerprint = _fingerprint([url, headers, proxy])
            if auth_fingerprint != self._auth_fingerprint:
                await self.aclose()
                self._auth_fingerprint = auth_fingerprint
                self._http_only = False
            if self._http_only:
                return None
            try:
                for attempt in range(2):
                    if self._connection is None or self._connection.state is not State.OPEN:
                        await self.aclose()
                        ws_headers = {
                            key: value for key, value in headers.items()
                            if key.lower() not in {"accept", "content-type", "user-agent", "openai-beta"}
                        }
                        ws_headers["OpenAI-Beta"] = _WEBSOCKET_BETA
                        try:
                            self._connection = await connect(
                                url.replace("https://", "wss://", 1).replace("http://", "ws://", 1),
                                additional_headers=ws_headers,
                                user_agent_header=headers.get("User-Agent"),
                                proxy=proxy if proxy else True,
                                ssl=verify if url.startswith("https://") else None,
                                open_timeout=15,
                                close_timeout=2,
                                max_size=None,
                                compression="deflate",
                            )
                        except InvalidStatus as exc:
                            if exc.response.status_code != 426:
                                try:
                                    raw: object = json.loads(exc.response.body)
                                except ValueError:
                                    raw = {}
                                raise CodexWebSocketError(
                                    {
                                        **(cast(dict[str, Any], raw) if isinstance(raw, dict) else {}),
                                        "headers": dict(exc.response.headers),
                                    },
                                    exc.response.status_code,
                                ) from None
                            self._http_only = True
                            return None
                        except (OSError, TimeoutError, ProxyError, ImportError):
                            # No model input was sent. The proxy may support HTTP but reject upgrades.
                            self._http_only = True
                            logger.info("Codex WebSocket connection unavailable; using HTTP for this session")
                            return None

                    input_items = cast(list[dict[str, Any]], body["input"])
                    properties = {
                        key: value for key, value in body.items()
                        if key not in {"input", "stream", "background", "previous_response_id", "type"}
                    }
                    properties_fingerprint = _fingerprint(properties)
                    can_continue = (
                        self._response_id is not None
                        and properties_fingerprint == self._properties_fingerprint
                        and len(input_items) >= self._prefix_length
                        and _input_fingerprint(input_items[:self._prefix_length]) == self._prefix_fingerprint
                    )
                    payload = {
                        **properties,
                        "type": "response.create",
                        "input": input_items[self._prefix_length:] if can_continue else input_items,
                    }
                    if can_continue:
                        payload["previous_response_id"] = self._response_id
                    capture = ResponsesStreamCapture()
                    response_started = False

                    async def observe_event(event: dict[str, Any]) -> None:
                        nonlocal response_started
                        event_type = event.get("type")
                        if isinstance(event_type, str) and event_type.startswith("response."):
                            response_started = True

                    try:
                        await self._connection.send(json.dumps(payload, ensure_ascii=False))
                        content, tool_calls, finish_reason, usage, reasoning = await consume_responses_events(
                            self._events(self._connection),
                            on_content_delta=on_content_delta,
                            on_tool_call_delta=on_tool_call_delta,
                            on_reasoning_delta=on_thinking_delta,
                            on_response_event=observe_event,
                            capture=capture,
                        )
                    except CodexWebSocketError as exc:
                        if attempt == 0 and not response_started and (
                            (can_continue and exc.error_code == "previous_response_not_found")
                            or exc.error_code == "websocket_connection_limit_reached"
                        ):
                            await self.aclose()
                            continue
                        raise
                    except (ConnectionClosed, OSError) as exc:
                        raise ConnectionError("Codex WebSocket connection interrupted") from exc
                    result = LLMResponse(
                        content=content, tool_calls=tool_calls, finish_reason=finish_reason,
                        usage=usage, reasoning_content=reasoning,
                    )
                    response_id = capture.response.get("id") if capture.response is not None else None
                    if capture.completed and is_replayable_finish_reason(finish_reason):
                        result.provider_state = build_responses_state(
                            provider=f"openai_codex:{url.rstrip('/')}",
                            model=str(body.get("model") or ""),
                            input_items=input_items,
                            output_items=capture.output_items,
                            usage=usage,
                        )
                        self._properties_fingerprint = properties_fingerprint
                        items = [*input_items, *capture.output_items]
                        self._prefix_length = len(items)
                        self._prefix_fingerprint = _input_fingerprint(items)
                        self._response_id = response_id if isinstance(response_id, str) and response_id else None
                    else:
                        self._response_id = None
                    return result
            except BaseException:
                # An interrupted response must not leave events queued for the next caller.
                await self.aclose()
                raise
        raise ConnectionError("Codex WebSocket continuation could not be recovered")

    async def _events(self, connection: ClientConnection) -> AsyncIterator[dict[str, Any]]:
        while True:
            try:
                data = await asyncio.wait_for(connection.recv(), resolve_stream_idle_timeout_s())
            except (ConnectionClosed, OSError) as exc:
                raise ConnectionError("Codex WebSocket connection closed before completion") from exc
            try:
                raw: object = json.loads(data)
            except ValueError:
                raise ConnectionError("Invalid Codex WebSocket response") from None
            if not isinstance(raw, dict):
                raise ConnectionError("Invalid Codex WebSocket response")
            event = cast(dict[str, Any], raw)
            if event.get("type") in {"error", "response.failed"}:
                raise CodexWebSocketError(event)
            yield event
