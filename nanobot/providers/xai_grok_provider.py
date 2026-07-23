"""xAI subscription provider with capability-gated hosted X Search."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
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
    XAIToken,
    get_xai_oauth_token,
)

DEFAULT_XAI_GROK_URL = "https://cli-chat-proxy.grok.com/v1/responses"
DEFAULT_XAI_GROK_MODELS_URL = "https://cli-chat-proxy.grok.com/v1/models"
DEFAULT_XAI_GROK_MODEL = "xai-grok/grok-4.5"
_MODEL_CAPABILITIES_TTL_S = 5 * 60
_MAX_ERROR_BODY_CHARS = 1000
_SENSITIVE_ERROR_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "idtoken",
    "refreshtoken",
}


class XAIGrokProvider(LLMProvider):
    """Call xAI's subscription proxy and expose supported hosted tools."""

    supports_progress_deltas = True

    def __init__(
        self,
        default_model: str = DEFAULT_XAI_GROK_MODEL,
        proxy: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ):
        super().__init__(api_key=None, api_base=None)
        self.default_model = default_model
        self.proxy = proxy or None
        self._extra_body = dict(extra_body or {})
        self._model_capabilities: dict[str, bool] | None = None
        self._model_capabilities_fetched_at = 0.0

    async def _supports_backend_search(self, token: XAIToken, model: str) -> bool:
        now = time.monotonic()
        capabilities = self._model_capabilities
        if (
            capabilities is None
            or now - self._model_capabilities_fetched_at >= _MODEL_CAPABILITIES_TTL_S
        ):
            try:
                capabilities = await _fetch_xai_model_capabilities(
                    DEFAULT_XAI_GROK_MODELS_URL,
                    _build_model_headers(token),
                    proxy=self.proxy,
                )
            except Exception as exc:
                logger.warning(
                    "xAI model capability lookup failed; hosted X Search disabled for model {}: "
                    "type={} error={}",
                    model,
                    type(exc).__name__,
                    str(exc).strip() or "unexpected error",
                )
                capabilities = {}
                self._model_capabilities = capabilities
                self._model_capabilities_fetched_at = now
            else:
                self._model_capabilities = capabilities
                self._model_capabilities_fetched_at = now
        return capabilities.get(model, False)

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

        stage = "oauth_token"
        try:
            token = await asyncio.to_thread(get_xai_oauth_token, proxy=self.proxy)
            stage = "model_capabilities"
            supports_backend_search = await self._supports_backend_search(token, wire_model)
            converted_tools = convert_tools(tools or [])
            if supports_backend_search:
                converted_tools = [
                    tool for tool in converted_tools if tool.get("name") != "x_search"
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

            headers = _build_headers(token.access, wire_model)
            stage = "xai_request"
            try:
                result = await _request_xai(
                    DEFAULT_XAI_GROK_URL,
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
                self._model_capabilities = None
                self._model_capabilities_fetched_at = 0.0
                headers = _build_headers(token.access, wire_model)
                stage = "xai_request_retry"
                result = await _request_xai(
                    DEFAULT_XAI_GROK_URL,
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
                "error_type={} error_code={} response_body={}",
                stage,
                type(exc).__name__,
                response.error_should_retry,
                response.error_status_code,
                response.error_type,
                response.error_code,
                getattr(exc, "response_body", None),
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
    if model.startswith("xai-grok/") or model.startswith("xai_grok/"):
        return model.split("/", 1)[1]
    return model


def _build_reasoning_options(reasoning_effort: str | None) -> dict[str, str]:
    options = {"summary": "concise"}
    if reasoning_effort and reasoning_effort.lower() != "none":
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


def _build_model_headers(token: XAIToken) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token.access}",
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-grok-client-version": XAI_CLIENT_VERSION,
        "x-grok-client-identifier": "nanobot",
        "x-grok-client-mode": "headless",
        "User-Agent": f"nanobot/{__version__} (python)",
        "accept": "application/json",
    }
    claims = _decode_access_token_claims(token.access)
    user_id = claims.get("sub")
    if claims.get("principal_type") == "Team":
        user_id = claims.get("principal_id") or user_id
    if isinstance(user_id, str) and user_id:
        headers["x-userid"] = user_id
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        email = token.account_id if token.account_id and "@" in token.account_id else None
    if email:
        headers["x-email"] = email
    return headers


def _decode_access_token_claims(token: str) -> dict[str, Any]:
    """Read identity hints from the signed token; the server still authenticates it."""
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return {}
    payload = parts[1]
    try:
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded)
    except (ValueError, TypeError):
        return {}
    return claims if isinstance(claims, dict) else {}


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
        response_body: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.error_type = error_type
        self.error_code = error_code
        self.should_retry = should_retry
        self.response_body = response_body


async def _fetch_xai_model_capabilities(
    url: str,
    headers: dict[str, str],
    *,
    proxy: str | None = None,
) -> dict[str, bool]:
    client_kwargs: dict[str, Any] = {"timeout": 10.0, "follow_redirects": False}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    async with httpx.AsyncClient(**client_kwargs) as client:
        response = await client.get(url, headers=headers)
    if response.status_code != 200:
        raw = response.content.decode("utf-8", "ignore")
        raise _build_xai_http_error(response.status_code, response.headers, raw)
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("xAI model catalog returned invalid JSON.") from exc
    return _parse_xai_model_capabilities(payload)


def _parse_xai_model_capabilities(payload: Any) -> dict[str, bool]:
    if isinstance(payload, dict):
        rows = payload.get("data")
        if not isinstance(rows, list):
            rows = payload.get("models")
    else:
        rows = payload
    if not isinstance(rows, list):
        return {}

    capabilities: dict[str, bool] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
        support_value = row.get("supportsBackendSearch")
        if not isinstance(support_value, bool):
            support_value = row.get("supports_backend_search")
        if not isinstance(support_value, bool):
            support_value = meta.get("supportsBackendSearch")
        if not isinstance(support_value, bool):
            support_value = meta.get("supports_backend_search")
        supports_backend_search = support_value if isinstance(support_value, bool) else False

        identifiers = (
            row.get("model"),
            row.get("modelId"),
            row.get("id"),
            meta.get("model"),
            meta.get("modelId"),
        )
        for identifier in identifiers:
            if isinstance(identifier, str) and identifier.strip():
                capabilities[_strip_model_prefix(identifier.strip())] = supports_backend_search
    return capabilities


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
    async def _on_response_event(event: dict[str, Any]) -> None:
        hosted_event = _xai_hosted_tool_event(event)
        if hosted_event is not None and on_tool_call_delta is not None:
            await on_tool_call_delta(hosted_event)

    client_kwargs: dict[str, Any] = {"timeout": resolve_stream_idle_timeout_s()}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    async with httpx.AsyncClient(**client_kwargs) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                content = await response.aread()
                raw = content.decode("utf-8", "ignore")
                raise _build_xai_http_error(response.status_code, response.headers, raw)
            return await consume_sse_with_reasoning(
                response,
                on_content_delta=on_content_delta,
                on_tool_call_delta=on_tool_call_delta,
                on_reasoning_delta=on_thinking_delta,
                on_response_event=_on_response_event if on_tool_call_delta else None,
            )


def _xai_hosted_tool_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = event.get("type")
    if event_type == "response.custom_tool_call_input.done":
        call_id = event.get("item_id") or event.get("call_id") or event.get("id")
        if not call_id:
            return None
        return {
            "kind": "hosted_tool",
            "phase": "start",
            "call_id": str(call_id),
            "name": "x_search",
            "arguments": _xai_hosted_tool_arguments(
                event.get("input", event.get("arguments"))
            ),
            "result": None,
        }

    if event_type != "response.output_item.done":
        return None
    item = event.get("item")
    if not isinstance(item, dict) or item.get("type") != "custom_tool_call":
        return None
    tool_name = item.get("name")
    if not isinstance(tool_name, str) or not tool_name.startswith("x_"):
        return None
    call_id = item.get("id") or item.get("call_id") or event.get("item_id")
    if not call_id:
        return None
    return {
        "kind": "hosted_tool",
        "phase": "end",
        "call_id": str(call_id),
        "name": "x_search",
        "arguments": _xai_hosted_tool_arguments(
            item.get("input", item.get("arguments"))
        ),
        # Keep the useful search subtype, but do not persist large hosted results
        # in WebUI activity messages. The model answer already carries citations.
        "result": {"name": tool_name},
    }


def _xai_hosted_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_xai_http_error(
    status_code: int,
    headers: httpx.Headers,
    raw: str,
) -> _XAIHTTPError:
    retry_after = LLMProvider._extract_retry_after_from_headers(headers)
    error_type, error_code = LLMProvider._extract_error_type_code(raw)
    response_body = _bounded_error_body(raw)
    return _XAIHTTPError(
        _friendly_error(status_code, response_body),
        status_code=status_code,
        retry_after=retry_after,
        error_type=error_type,
        error_code=error_code,
        should_retry=_should_retry_status(status_code, error_type, error_code, raw),
        response_body=response_body,
    )


def _bounded_error_body(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        pass
    else:
        text = json.dumps(
            _redact_error_payload(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    text = re.sub(r"(?i)(bearer\s+)[a-z0-9._~+/=-]+", r"\1[REDACTED]", text)
    text = " ".join(text.split())
    if len(text) > _MAX_ERROR_BODY_CHARS:
        return f"{text[:_MAX_ERROR_BODY_CHARS]}…"
    return text


def _redact_error_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: "[REDACTED]" if _is_sensitive_error_key(key) else _redact_error_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_redact_error_payload(value) for value in payload]
    return payload


def _is_sensitive_error_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return normalized in _SENSITIVE_ERROR_KEYS


def _friendly_error(status_code: int, response_body: str | None = None) -> str:
    if status_code == 401:
        message = "xAI rejected the login. Sign in again with `nanobot provider login xai-grok`."
    elif status_code == 403:
        message = "This xAI account or subscription cannot access the Grok subscription endpoint."
    elif status_code == 426:
        message = "xAI requires a newer Grok client version. Update nanobot and try again."
    elif status_code == 429:
        message = "xAI usage quota or rate limit reached. Please try again later."
    else:
        message = f"xAI subscription endpoint returned HTTP {status_code}."
    if response_body:
        return f"{message} Response body: {response_body}"
    return message


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
