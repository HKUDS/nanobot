"""xAI subscription provider with the hosted X Search tool enabled."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from loguru import logger

from nanobot import __version__
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
    resolve_stream_idle_timeout_s,
)
from nanobot.providers.openai_responses import (
    consume_sse_with_reasoning,
    convert_messages,
    convert_tools,
)
from nanobot.providers.xai_oauth import (
    XAI_CLIENT_VERSION,
    get_xai_oauth_token,
)

DEFAULT_XAI_OAUTH_URL = "https://cli-chat-proxy.grok.com/v1/responses"
DEFAULT_XAI_OAUTH_MODEL = "xai-oauth/grok-4.5"


class XAIOAuthProvider(LLMProvider):
    """Call xAI's subscription proxy and expose its server-side X Search."""

    supports_progress_deltas = True

    def __init__(
        self,
        default_model: str = DEFAULT_XAI_OAUTH_MODEL,
        proxy: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ):
        super().__init__(api_key=None, api_base=None)
        self.default_model = default_model
        self.proxy = proxy or None
        self._extra_body = dict(extra_body or {})

    async def _call_xai(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        wire_model = _strip_model_prefix(model or self.default_model)
        system_prompt, input_items = convert_messages(messages)
        converted_tools = [
            tool for tool in convert_tools(tools or []) if tool.get("name") != "x_search"
        ]
        converted_tools.append({"type": "x_search"})

        body: dict[str, Any] = {
            "model": wire_model,
            "store": False,
            "stream": True,
            "instructions": system_prompt,
            "input": input_items,
            "include": ["reasoning.encrypted_content"],
            "tools": converted_tools,
            "tool_choice": tool_choice or "auto",
            "parallel_tool_calls": True,
            "stream_tool_calls": True,
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "reasoning": _build_reasoning_options(reasoning_effort),
        }
        if self._extra_body:
            body.update(self._extra_body)

        stage = "oauth_token"
        try:
            token = await asyncio.to_thread(get_xai_oauth_token, proxy=self.proxy)
            headers = _build_headers(token.access, wire_model)
            stage = "xai_request"
            try:
                result = await _request_xai(
                    DEFAULT_XAI_OAUTH_URL,
                    headers,
                    body,
                    proxy=self.proxy,
                    on_content_delta=on_content_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                )
            except _XAIHTTPError as exc:
                if exc.status_code != 401:
                    raise
                stage = "oauth_refresh"
                token = await asyncio.to_thread(
                    get_xai_oauth_token,
                    proxy=self.proxy,
                    force_refresh=True,
                )
                headers = _build_headers(token.access, wire_model)
                stage = "xai_request_retry"
                result = await _request_xai(
                    DEFAULT_XAI_OAUTH_URL,
                    headers,
                    body,
                    proxy=self.proxy,
                    on_content_delta=on_content_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                )

            content, tool_calls, finish_reason, usage, reasoning_content = result
            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                reasoning_content=reasoning_content,
            )
        except Exception as exc:
            response = _xai_error_response(exc)
            logger.warning(
                "xAI subscription request failed: stage={} type={} retryable={} status={} "
                "error_type={} error_code={}",
                stage,
                type(exc).__name__,
                response.error_should_retry,
                response.error_status_code,
                response.error_type,
                response.error_code,
            )
            return response

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        return await self._call_xai(
            messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        return await self._call_xai(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
            on_content_delta,
            on_thinking_delta,
            on_tool_call_delta,
        )

    def get_default_model(self) -> str:
        return self.default_model


def _strip_model_prefix(model: str) -> str:
    if model.startswith("xai-oauth/") or model.startswith("xai_oauth/"):
        return model.split("/", 1)[1]
    return model


def _build_reasoning_options(reasoning_effort: str | None) -> dict[str, str]:
    options = {"summary": "concise"}
    if reasoning_effort:
        options["effort"] = reasoning_effort
    return options


def _build_headers(token: str, model: str) -> dict[str, str]:
    conversation_id = str(uuid.uuid4())
    return {
        "Authorization": f"Bearer {token}",
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-authenticateresponse": "authenticate-response",
        "x-grok-client-version": XAI_CLIENT_VERSION,
        "x-grok-client-identifier": "nanobot",
        "x-grok-client-mode": "headless",
        "x-grok-conv-id": conversation_id,
        "x-grok-req-id": str(uuid.uuid4()),
        "x-grok-model-override": model,
        "x-grok-session-id": conversation_id,
        "x-grok-agent-id": str(uuid.uuid4()),
        "User-Agent": f"nanobot/{__version__} (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


class _XAIHTTPError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        retry_after: float | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        should_retry: bool | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.error_type = error_type
        self.error_code = error_code
        self.should_retry = should_retry


async def _request_xai(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    proxy: str | None = None,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> tuple[str, list[ToolCallRequest], str, dict[str, int], str | None]:
    client_kwargs: dict[str, Any] = {"timeout": resolve_stream_idle_timeout_s()}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    async with httpx.AsyncClient(**client_kwargs) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                content = await response.aread()
                raw = content.decode("utf-8", "ignore")
                retry_after = LLMProvider._extract_retry_after_from_headers(response.headers)
                error_type, error_code = LLMProvider._extract_error_type_code(raw)
                raise _XAIHTTPError(
                    _friendly_error(response.status_code),
                    status_code=response.status_code,
                    retry_after=retry_after,
                    error_type=error_type,
                    error_code=error_code,
                    should_retry=_should_retry_status(
                        response.status_code, error_type, error_code, raw
                    ),
                )
            return await consume_sse_with_reasoning(
                response,
                on_content_delta=on_content_delta,
                on_tool_call_delta=on_tool_call_delta,
                on_reasoning_delta=on_thinking_delta,
            )


def _friendly_error(status_code: int) -> str:
    if status_code == 401:
        return "xAI rejected the login. Sign in again with `nanobot provider login xai-oauth`."
    if status_code == 403:
        return "This xAI account or subscription cannot access the Grok subscription endpoint."
    if status_code == 429:
        return "xAI usage quota or rate limit reached. Please try again later."
    return f"xAI subscription endpoint returned HTTP {status_code}."


def _xai_error_response(exc: Exception) -> LLMResponse:
    status_code = getattr(exc, "status_code", None)
    should_retry = getattr(exc, "should_retry", None)
    error_kind: str | None = None
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
        error_kind = "timeout"
        should_retry = True if should_retry is None else should_retry
    elif isinstance(exc, (httpx.NetworkError, httpx.TransportError)):
        error_kind = "connection"
        should_retry = True if should_retry is None else should_retry
    elif isinstance(exc, _XAIHTTPError):
        error_kind = "http"
    if status_code is not None and should_retry is None:
        should_retry = _should_retry_status(
            int(status_code),
            getattr(exc, "error_type", None),
            getattr(exc, "error_code", None),
            None,
        )
    message = str(exc).strip() or "unexpected error"
    retry_after = getattr(exc, "retry_after", None)
    return LLMResponse(
        content=f"Error calling xAI ({type(exc).__name__}): {message}",
        finish_reason="error",
        retry_after=retry_after,
        error_status_code=int(status_code) if status_code is not None else None,
        error_kind=error_kind,
        error_type=getattr(exc, "error_type", None),
        error_code=getattr(exc, "error_code", None),
        error_retry_after_s=retry_after,
        error_should_retry=should_retry,
    )


def _should_retry_status(
    status_code: int,
    error_type: str | None,
    error_code: str | None,
    content: str | None,
) -> bool:
    if status_code == 429:
        return LLMProvider._is_retryable_429_response(
            LLMResponse(
                content=content or "",
                finish_reason="error",
                error_status_code=status_code,
                error_type=error_type,
                error_code=error_code,
            )
        )
    return status_code in LLMProvider._RETRYABLE_STATUS_CODES or status_code >= 500
