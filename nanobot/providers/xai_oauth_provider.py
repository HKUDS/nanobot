"""xAI Grok OAuth-backed Responses provider."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.openai_responses import consume_sse, convert_messages, convert_tools
from nanobot.providers.xai_oauth_auth import (
    DEFAULT_XAI_API_BASE,
    XaiOAuthCredential,
    resolve_xai_oauth_credential,
)

DEFAULT_XAI_MODEL = "xai-oauth/grok-4.3"


class XaiOAuthProvider(LLMProvider):
    """Use a SuperGrok OAuth session to call xAI's Responses API."""

    supports_progress_deltas = True

    def __init__(self, default_model: str = DEFAULT_XAI_MODEL):
        super().__init__(api_key=None, api_base=DEFAULT_XAI_API_BASE)
        self.default_model = default_model

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
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        body = _build_xai_responses_body(
            messages=messages,
            tools=tools,
            model=model or self.default_model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
        )
        try:
            credential = await asyncio.to_thread(resolve_xai_oauth_credential)
            try:
                content, tool_calls, finish_reason = await _request_xai(
                    credential,
                    body,
                    on_content_delta=on_content_delta,
                    on_tool_call_delta=on_tool_call_delta,
                )
            except _XaiHTTPError as exc:
                if exc.status_code != 401:
                    raise
                credential = await asyncio.to_thread(resolve_xai_oauth_credential, force_refresh=True)
                content, tool_calls, finish_reason = await _request_xai(
                    credential,
                    body,
                    on_content_delta=on_content_delta,
                    on_tool_call_delta=on_tool_call_delta,
                )
            return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=finish_reason)
        except Exception as exc:
            msg = f"Error calling xAI Grok OAuth: {exc}"
            retry_after = getattr(exc, "retry_after", None) or self._extract_retry_after(msg)
            return LLMResponse(content=msg, finish_reason="error", retry_after=retry_after)

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
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
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
        _ = on_thinking_delta
        return await self._call_xai(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
            on_content_delta,
            on_tool_call_delta,
        )

    def get_default_model(self) -> str:
        return self.default_model


def _strip_model_prefix(model: str) -> str:
    for prefix in ("xai-oauth/", "xai_oauth/", "grok-oauth/", "grok_oauth/"):
        if model.startswith(prefix):
            return model.split("/", 1)[1]
    return model


def _build_xai_responses_body(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    model: str,
    max_tokens: int,
    temperature: float,
    reasoning_effort: str | None,
    tool_choice: str | dict[str, Any] | None,
) -> dict[str, Any]:
    system_prompt, input_items = convert_messages(LLMProvider._sanitize_empty_content(messages))
    if system_prompt:
        input_items = [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            *input_items,
        ]

    body: dict[str, Any] = {
        "model": _strip_model_prefix(model),
        "store": False,
        "stream": True,
        "input": input_items,
        "tool_choice": tool_choice or "auto",
        "parallel_tool_calls": True,
    }
    if max_tokens:
        body["max_output_tokens"] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature
    if reasoning_effort and reasoning_effort.lower() != "none":
        body["reasoning"] = {"effort": reasoning_effort}
    if tools:
        body["tools"] = convert_tools(tools)
    return body


class _XaiHTTPError(RuntimeError):
    def __init__(self, message: str, *, status_code: int, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


async def _request_xai(
    credential: XaiOAuthCredential,
    body: dict[str, Any],
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> tuple[str, list[ToolCallRequest], str]:
    url = credential.api_base.rstrip("/") + "/responses"
    headers = {
        "Authorization": f"Bearer {credential.access_token}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "nanobot (python)",
    }
    timeout = httpx.Timeout(120.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=True) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                raw = await response.aread()
                retry_after = LLMProvider._extract_retry_after_from_headers(response.headers)
                raise _XaiHTTPError(
                    _friendly_error(response.status_code, raw.decode("utf-8", "ignore")),
                    status_code=response.status_code,
                    retry_after=retry_after,
                )
            return await consume_sse(response, on_content_delta, on_tool_call_delta)


def _friendly_error(status_code: int, raw: str) -> str:
    if status_code == 401:
        return "xAI OAuth session expired or was revoked. Run: nanobot provider login xai-oauth"
    if status_code == 403:
        return (
            "xAI accepted the OAuth token, but this account is not entitled for the requested "
            "Grok API capability yet. Check the active Grok subscription and selected model."
        )
    if status_code == 429:
        return "xAI Grok subscription quota or rate limit was reached. Please try again later."
    return f"HTTP {status_code}: {raw[:500]}"
