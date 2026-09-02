"""xAI subscription provider with capability-gated hosted X Search."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
from loguru import logger

from nanobot import __version__
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ToolCallRequest,
    resolve_stream_idle_timeout_s,
)
from nanobot.providers.oauth_model_catalog import OAuthModelCatalog, OAuthModelCatalogSnapshot
from nanobot.providers.openai_responses import (
    consume_sse_with_reasoning,
    convert_messages,
    convert_tools,
)
from nanobot.providers.registry import ProviderModelSpec, find_by_name
from nanobot.providers.xai_oauth import (
    XAI_CLIENT_VERSION,
    get_xai_oauth_login_status,
    get_xai_oauth_storage_path,
    get_xai_oauth_token,
)

DEFAULT_XAI_GROK_MODEL = "xai-grok/grok-4.6"
DEFAULT_XAI_GROK_URL = "https://cli-chat-proxy.grok.com/v1/responses"
DEFAULT_XAI_GROK_MODELS_URL = "https://cli-chat-proxy.grok.com/v1/models"
_HOSTED_SEARCH_MAX_TURNS = 5
_MAX_ERROR_BODY_CHARS = 1000
_SENSITIVE_ERROR_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "idtoken",
    "refreshtoken",
}


def _is_hosted_x_search_tool(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return cast(dict[object, object], value).get("type") == "x_search"


def _is_named_x_search_tool(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    record = cast(dict[object, object], value)
    return record.get("type") == "function" and record.get("name") == "x_search"


class XAIGrokProvider(LLMProvider):
    """Call xAI's subscription proxy and expose supported hosted tools."""

    # An incomplete hosted-tool stream can already have emitted answer text. Let the
    # provider close that stream segment before its one bounded recovery attempt.
    supports_stream_recover_callback = True

    def __init__(
        self,
        default_model: str = DEFAULT_XAI_GROK_MODEL,
        proxy: str | None = None,
        extra_body: dict[str, Any] | None = None,
        *,
        provider_name: str = "xai_grok",
    ):
        super().__init__(api_key=None, api_base=None, provider_name=provider_name)
        self.default_model = default_model
        self.proxy = proxy or None
        self._extra_body = dict(extra_body or {})

    async def _supports_backend_search(self, model: str) -> bool:
        catalog = await asyncio.to_thread(
            get_xai_grok_model_catalog,
            self.proxy,
        )
        if catalog.message:
            logger.warning(
                "xAI model catalog unavailable; hosted X Search disabled unless cached: {}",
                catalog.message,
            )
        info = catalog.find(model)
        return bool(info and info.supports_backend_search)

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
        on_stream_recover: Callable[[], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        wire_model = _strip_model_prefix(model or self.default_model)
        system_prompt, input_items = convert_messages(messages)

        stage = "oauth_token"
        try:
            token = await asyncio.to_thread(get_xai_oauth_token, proxy=self.proxy)
            configured_tools = self._extra_body.get("tools")
            tools_are_explicit = "tools" in self._extra_body
            configured_hosted_search = isinstance(configured_tools, list) and any(
                _is_hosted_x_search_tool(tool) for tool in cast(list[object], configured_tools)
            )
            supports_backend_search = False
            if not tools_are_explicit:
                stage = "model_capabilities"
                supports_backend_search = await self._supports_backend_search(wire_model)
            converted_tools = convert_tools(tools or [])
            if isinstance(configured_tools, list):
                converted_tools.extend(cast(list[dict[str, Any]], configured_tools))
            if supports_backend_search or configured_hosted_search:
                converted_tools = [
                    tool for tool in converted_tools if not _is_named_x_search_tool(tool)
                ]
            if supports_backend_search:
                converted_tools.append({"type": "x_search"})

            hosted_search_enabled = supports_backend_search or configured_hosted_search

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
            if hosted_search_enabled:
                # xAI's global default is intentionally unspecified. Five turns is
                # their documented balanced setting and prevents a search from
                # stopping after a single unsuccessful lookup.
                body["max_turns"] = _HOSTED_SEARCH_MAX_TURNS
            if self._extra_body:
                body.update(
                    {key: value for key, value in self._extra_body.items() if key != "tools"}
                )
                if tools_are_explicit and not isinstance(configured_tools, list):
                    body["tools"] = configured_tools

            headers = _build_headers(token.access, wire_model)
            stage = "xai_request"
            auth_retried = False
            hosted_tool_retried = False
            retry_usage: LLMUsage | None = None
            while True:
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
                    break
                except _XAIHTTPError as exc:
                    if exc.status_code != 401 or auth_retried:
                        raise
                    auth_retried = True
                    stage = "oauth_refresh"
                    token = await asyncio.to_thread(
                        get_xai_oauth_token,
                        proxy=self.proxy,
                        force_refresh=True,
                    )
                    headers = _build_headers(token.access, wire_model)
                    stage = "xai_request_after_oauth_refresh"
                except _XAIIncompleteHostedToolError as exc:
                    retry_usage = _combine_usage(retry_usage, exc.usage)
                    cannot_recover_stream = exc.stream_output_emitted and on_stream_recover is None
                    if hosted_tool_retried or cannot_recover_stream:
                        exc.usage = retry_usage
                        raise
                    hosted_tool_retried = True
                    stage = "hosted_tool_recovery"
                    logger.warning(
                        "xAI response ended with unfinished hosted tool(s): {}; retrying once",
                        ", ".join(exc.tool_names),
                    )
                    if on_stream_recover is not None:
                        await on_stream_recover()
                    headers = _build_headers(token.access, wire_model)

            content, tool_calls, finish_reason, usage, reasoning_content = result
            usage = _combine_usage(retry_usage, usage)
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
        on_stream_recover: Callable[[], Awaitable[None]] | None = None,
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
            on_stream_recover,
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


def _combine_usage(left: LLMUsage | None, right: LLMUsage | None) -> LLMUsage | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


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
        response_body: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.error_type = error_type
        self.error_code = error_code
        self.should_retry = should_retry
        self.response_body = response_body


class _XAIIncompleteHostedToolError(RuntimeError):
    """A nominally successful xAI stream ended before a hosted tool did."""

    should_retry = False  # _call_xai already performs the one safe recovery attempt.

    def __init__(
        self,
        active_tools: list[dict[str, Any]],
        *,
        usage: LLMUsage | None,
        stream_output_emitted: bool = False,
    ) -> None:
        names = [str(event.get("name") or "hosted_tool") for event in active_tools]
        super().__init__(
            "xAI ended the response before its hosted tool completed: " + ", ".join(names)
        )
        self.tool_names = tuple(names)
        self.usage = usage
        self.stream_output_emitted = stream_output_emitted


async def _request_xai(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    proxy: str | None = None,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> tuple[str, list[ToolCallRequest], str, LLMUsage | None, str | None]:
    active_hosted_tools: dict[str, dict[str, Any]] = {}
    stream_output_emitted = False

    async def _forward_content_delta(delta: str) -> None:
        nonlocal stream_output_emitted
        if delta:
            stream_output_emitted = True
        if on_content_delta is not None:
            await on_content_delta(delta)

    async def _forward_thinking_delta(delta: str) -> None:
        nonlocal stream_output_emitted
        if delta:
            stream_output_emitted = True
        if on_thinking_delta is not None:
            await on_thinking_delta(delta)

    async def _track_and_forward_tool_event(event: dict[str, Any]) -> None:
        if event.get("kind") == "hosted_tool":
            call_id = event.get("call_id")
            if call_id:
                call_id = str(call_id)
                if event.get("phase") == "start":
                    active_hosted_tools[call_id] = dict(event)
                elif event.get("phase") in {"end", "error"}:
                    active_hosted_tools.pop(call_id, None)
        if on_tool_call_delta is not None:
            await on_tool_call_delta(event)

    async def _on_response_event(event: dict[str, Any]) -> None:
        hosted_event = _xai_hosted_tool_event(event)
        if hosted_event is not None:
            await _track_and_forward_tool_event(hosted_event)

    client_kwargs: dict[str, Any] = {"timeout": resolve_stream_idle_timeout_s()}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    async with httpx.AsyncClient(**client_kwargs) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                content = await response.aread()
                raw = content.decode("utf-8", "ignore")
                raise _build_xai_http_error(response.status_code, response.headers, raw)
            result = await consume_sse_with_reasoning(
                response,
                on_content_delta=(_forward_content_delta if on_content_delta is not None else None),
                # Always observe tool events so protocol validation also works for
                # non-streaming callers that did not request UI progress callbacks.
                on_tool_call_delta=_track_and_forward_tool_event,
                on_reasoning_delta=(
                    _forward_thinking_delta if on_thinking_delta is not None else None
                ),
                on_response_event=_on_response_event,
            )
            if result[2] != "error" and active_hosted_tools:
                active = list(active_hosted_tools.values())
                for event in active:
                    await _track_and_forward_tool_event(
                        {
                            **event,
                            "phase": "error",
                            "result": None,
                            "error": "xAI ended the response before this hosted tool completed.",
                        }
                    )
                raise _XAIIncompleteHostedToolError(
                    active,
                    usage=result[3],
                    stream_output_emitted=stream_output_emitted,
                )
            return result


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
            "arguments": _xai_hosted_tool_arguments(event.get("input", event.get("arguments"))),
            "result": None,
        }

    if event_type not in {"response.output_item.added", "response.output_item.done"}:
        return None
    item = event.get("item")
    if not isinstance(item, dict):
        return None
    item = cast(dict[str, Any], item)
    item_type = item.get("type")
    if item_type == "x_search_call":
        call_id = item.get("id") or item.get("call_id") or event.get("item_id")
        if not call_id:
            return None
        phase = "start" if event_type == "response.output_item.added" else "end"
        return {
            "kind": "hosted_tool",
            "phase": phase,
            "call_id": str(call_id),
            "name": "x_search",
            "arguments": _xai_hosted_tool_arguments(item.get("action")),
            "result": (
                {"status": str(item.get("status") or "completed")} if phase == "end" else None
            ),
        }
    if event_type != "response.output_item.done" or item_type != "custom_tool_call":
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
        "arguments": _xai_hosted_tool_arguments(item.get("input", item.get("arguments"))),
        # Keep the useful search subtype, but do not persist large hosted results
        # in WebUI activity messages. The model answer already carries citations.
        "result": {"name": tool_name},
    }


def _xai_hosted_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}


def _build_xai_http_error(
    status_code: int,
    headers: httpx.Headers,
    raw: str,
) -> _XAIHTTPError:
    retry_after = LLMProvider._extract_retry_after_from_headers(headers)  # pyright: ignore[reportPrivateUsage]
    error_type, error_code = LLMProvider._extract_error_type_code(raw)  # pyright: ignore[reportPrivateUsage]
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
        redacted: dict[str, Any] = {}
        payload_mapping: dict[str, Any] = cast(dict[str, Any], payload)
        for key in payload_mapping:
            value = payload_mapping[key]
            redacted[key] = (
                "[REDACTED]" if _is_sensitive_error_key(key) else _redact_error_payload(value)
            )
        return redacted
    if isinstance(payload, list):
        return [_redact_error_payload(value) for value in cast(list[Any], payload)]
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
    elif isinstance(exc, _XAIIncompleteHostedToolError):
        error_kind = "provider"
    if status_code is not None and should_retry is None:
        should_retry = _should_retry_status(
            int(status_code),
            getattr(exc, "error_type", None),
            getattr(exc, "error_code", None),
            None,
        )
    message = str(exc).strip() or "unexpected error"
    retry_after = getattr(exc, "retry_after", None)
    usage = getattr(exc, "usage", None)
    return LLMResponse(
        content=f"Error calling xAI ({type(exc).__name__}): {message}",
        finish_reason="error",
        usage=usage if isinstance(usage, LLMUsage) else None,
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
        return LLMProvider._is_retryable_429_response(  # pyright: ignore[reportPrivateUsage]
            LLMResponse(
                content=content or "",
                finish_reason="error",
                error_status_code=status_code,
                error_type=error_type,
                error_code=error_code,
            )
        )
    return status_code in LLMProvider._RETRYABLE_STATUS_CODES or status_code >= 500  # pyright: ignore[reportPrivateUsage]


def get_xai_grok_model_catalog(proxy: str | None = None) -> OAuthModelCatalogSnapshot:
    token = get_xai_oauth_login_status()
    account_key = _catalog_account_key(getattr(token, "account_id", None))
    cache_key = f"{get_xai_oauth_storage_path()}\0{account_key}\0{proxy or ''}"
    return _XAI_GROK_MODEL_CATALOG.get(cache_key=cache_key, proxy=proxy)


def invalidate_xai_grok_model_catalog() -> None:
    _XAI_GROK_MODEL_CATALOG.invalidate()


def _fetch_xai_grok_models(proxy: str | None) -> tuple[ProviderModelSpec, ...]:
    token = get_xai_oauth_token(proxy=proxy)
    client_kwargs: dict[str, Any] = {"timeout": 10.0, "follow_redirects": False}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    with httpx.Client(**client_kwargs) as client:
        response = client.get(
            DEFAULT_XAI_GROK_MODELS_URL,
            headers=_build_xai_model_headers(token.access, token.account_id),
        )
    response.raise_for_status()
    return _parse_xai_grok_models(response.json())


def _parse_xai_grok_models(payload: Any) -> tuple[ProviderModelSpec, ...]:
    if isinstance(payload, dict):
        payload_mapping = cast(dict[str, Any], payload)
        rows: object = payload_mapping.get("data")
        if not isinstance(rows, list):
            rows = payload_mapping.get("models")
    else:
        rows = payload
    if not isinstance(rows, list):
        return ()

    fallback_models = _oauth_fallback_models("xai_grok")
    fallback_by_id = {model.id.split("/", 1)[-1]: model for model in fallback_models}
    models: list[ProviderModelSpec] = []
    seen: set[str] = set()
    for value in cast(list[object], rows):
        if not isinstance(value, dict):
            continue
        row = cast(dict[str, Any], value)
        meta = _catalog_mapping(row.get("_meta"))
        raw_id = next(
            (
                candidate.strip()
                for candidate in (
                    row.get("id"),
                    row.get("model"),
                    row.get("modelId"),
                    row.get("name"),
                    meta.get("id"),
                    meta.get("model"),
                    meta.get("modelId"),
                )
                if isinstance(candidate, str) and candidate.strip()
            ),
            None,
        )
        if raw_id is None:
            continue
        wire_id = raw_id.split("/", 1)[-1]
        if wire_id in seen:
            continue
        seen.add(wire_id)
        fallback = fallback_by_id.get(wire_id)
        label = _catalog_first_text(row, "display_name", "label", "name") or _catalog_first_text(
            meta,
            "display_name",
            "label",
            "name",
        )
        if not label or label == raw_id:
            label = fallback.label if fallback is not None else wire_id
        models.append(
            ProviderModelSpec(
                id=f"xai-grok/{wire_id}",
                label=label,
                description=(
                    _catalog_first_text(row, "description")
                    or _catalog_first_text(meta, "description")
                    or (fallback.description if fallback is not None else "")
                ),
                owned_by=(
                    _catalog_first_text(row, "owned_by", "owner", "organization")
                    or _catalog_first_text(meta, "owned_by", "owner", "organization")
                    or (fallback.owned_by if fallback is not None else "xAI")
                ),
                context_window=(
                    _catalog_positive_int(row, "context_window", "context_length")
                    or _catalog_positive_int(meta, "context_window", "context_length")
                    or (fallback.context_window if fallback is not None else None)
                ),
                reasoning_efforts=_catalog_reasoning_efforts(
                    row.get("reasoning_efforts", meta.get("reasoning_efforts"))
                ),
                supports_backend_search=_catalog_bool_field(
                    row,
                    "supports_backend_search",
                    "supportsBackendSearch",
                ),
            )
        )
    return tuple(models)


def _build_xai_model_headers(access_token: str, account_id: str | None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-grok-client-version": XAI_CLIENT_VERSION,
        "x-grok-client-identifier": "nanobot",
        "x-grok-client-mode": "headless",
        "User-Agent": f"nanobot/{__version__} (python)",
        "accept": "application/json",
    }
    claims = _decode_access_token_claims(access_token)
    user_id = claims.get("sub")
    if claims.get("principal_type") == "Team":
        user_id = claims.get("principal_id") or user_id
    if isinstance(user_id, str) and user_id:
        headers["x-userid"] = user_id
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        email = account_id if account_id and "@" in account_id else None
    if email:
        headers["x-email"] = email
    return headers


def _decode_access_token_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return {}
    try:
        decoded = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        claims = json.loads(decoded)
    except (ValueError, TypeError):
        return {}
    return cast(dict[str, Any], claims) if isinstance(claims, dict) else {}


def _oauth_fallback_models(provider_name: str) -> tuple[ProviderModelSpec, ...]:
    spec = find_by_name(provider_name)
    assert spec is not None
    return spec.builtin_models


def _catalog_account_key(account_id: object) -> str:
    value = account_id if isinstance(account_id, str) else ""
    return hashlib.sha256(value.encode()).hexdigest()[:16] if value else "anonymous"


def _catalog_mapping(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _catalog_first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _catalog_positive_int(row: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return None


def _catalog_bool_field(row: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            return value
    meta = row.get("_meta")
    return _catalog_bool_field(_catalog_mapping(meta), *keys) if isinstance(meta, dict) else False


def _catalog_reasoning_efforts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    efforts: list[str] = []
    for item in cast(list[object], value):
        if isinstance(item, str):
            effort = item.strip()
        elif isinstance(item, dict):
            effort = _catalog_first_text(cast(dict[str, Any], item), "effort", "value", "id")
        else:
            effort = ""
        if effort and effort not in efforts:
            efforts.append(effort)
    return tuple(efforts)


_XAI_GROK_MODEL_CATALOG = OAuthModelCatalog(
    fallback_models=_oauth_fallback_models("xai_grok"),
    fetch=_fetch_xai_grok_models,
)
