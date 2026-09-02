"""OpenAI Codex Responses Provider."""

# pyright: reportMissingTypeStubs=false, reportPrivateUsage=false

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
from loguru import logger
from oauth_cli_kit import get_token as get_codex_token
from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
from oauth_cli_kit.storage import FileTokenStorage

from nanobot import __version__
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCallContext,
    ProviderConversationState,
    resolve_stream_idle_timeout_s,
)
from nanobot.providers.oauth_model_catalog import (
    OAuthModelCatalog,
    OAuthModelCatalogSnapshot,
)
from nanobot.providers.openai_responses import (
    ResponsesStreamCapture,
    build_responses_compaction_state,
    build_responses_state,
    consume_sse_with_reasoning,
    convert_tools,
    is_compaction_compatibility_error,
    is_replayable_finish_reason,
    prepare_responses_input,
    resolve_compact_threshold,
    responses_state_context_tokens,
    responses_state_items,
    responses_state_matches,
)
from nanobot.providers.registry import ProviderModelSpec, find_by_name

DEFAULT_CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_OPENAI_CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
OPENAI_CODEX_CATALOG_CLIENT_VERSION = "0.144.0"
DEFAULT_ORIGINATOR = "nanobot"
_COMPACTION_RETAINED_CHAR_BUDGET = 256_000


class OpenAICodexProvider(LLMProvider):
    """Use Codex OAuth to call the Responses API."""

    def __init__(
        self,
        default_model: str = "openai-codex/gpt-5.6-sol",
        proxy: str | None = None,
        extra_body: dict[str, Any] | None = None,
        *,
        provider_name: str = "openai_codex",
    ):
        super().__init__(api_key=None, api_base=None, provider_name=provider_name)
        self.default_model = default_model
        self.proxy = proxy or None
        self._extra_body = dict(extra_body or {})
        self._native_compaction_available = True
        self._ssl_contexts: dict[bool, ssl.SSLContext] = {}

    def _ssl_context(self, *, verify: bool) -> ssl.SSLContext:
        """Reuse synchronous TLS setup across requests on the shared event loop."""
        context = self._ssl_contexts.get(verify)
        if context is None:
            context = httpx.create_ssl_context(
                verify=verify,
                trust_env=self.proxy is None,
            )
            self._ssl_contexts[verify] = context
        return context

    async def _call_codex(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        provider_context: ProviderCallContext | None = None,
    ) -> LLMResponse:
        """Shared request logic for both chat() and chat_stream()."""
        model = model or self.default_model
        sanitized_messages = self._sanitize_empty_content(messages)
        sanitized_state = (
            provider_context.conversation_state if provider_context is not None else None
        )
        if sanitized_state is not None:
            sanitized_state = sanitized_state.with_pending_messages(
                self._sanitize_empty_content(sanitized_state.pending_messages)
            )
        system_prompt, input_items, replayed = prepare_responses_input(
            sanitized_messages,
            state=sanitized_state,
            provider=self._responses_state_provider(),
            model=_strip_model_prefix(model),
        )
        session_id = provider_context.session_id if provider_context is not None else None
        session_routing_key = _prompt_cache_key(session_id) if session_id else None

        body: dict[str, Any] = {
            "model": _strip_model_prefix(model),
            "store": False,
            "stream": True,
            "instructions": system_prompt,
            "input": input_items,
            "text": {"verbosity": "medium"},
            "tool_choice": tool_choice or "auto",
            "parallel_tool_calls": True,
        }
        if session_routing_key:
            body["prompt_cache_key"] = session_routing_key
        body["include"] = ["reasoning.encrypted_content"]
        reasoning_options = _build_reasoning_options(reasoning_effort)
        if replayed and "gpt-5.6" in _strip_model_prefix(model).lower():
            reasoning_options = dict(reasoning_options or {})
            reasoning_options["context"] = "all_turns"
        if reasoning_options:
            body["reasoning"] = reasoning_options
        if tools:
            body["tools"] = convert_tools(tools)
        if self._extra_body:
            # Apply explicit provider overrides last, matching other provider backends.
            body.update(self._extra_body)
        effective_cache_key = body.get("prompt_cache_key")

        stage = "oauth_token"
        native_compaction_applied = False
        native_compaction_state: ProviderConversationState | None = None
        try:
            token = await asyncio.to_thread(get_codex_token, proxy=self.proxy)
            headers = _build_headers(
                cast(str, token.account_id),
                token.access,
                session_routing_key=(
                    effective_cache_key if isinstance(effective_cache_key, str) else None
                ),
            )

            async def _send(
                request_body: dict[str, Any],
                *,
                emit_deltas: bool,
            ) -> LLMResponse:
                wire_body = _without_response_item_ids(request_body)
                try:
                    return await _request_codex(
                        DEFAULT_CODEX_URL,
                        headers,
                        wire_body,
                        verify=self._ssl_context(verify=True),
                        proxy=self.proxy,
                        on_content_delta=on_content_delta if emit_deltas else None,
                        on_thinking_delta=on_thinking_delta if emit_deltas else None,
                        on_tool_call_delta=on_tool_call_delta if emit_deltas else None,
                    )
                except Exception as exc:
                    if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                        raise
                    logger.warning(
                        "SSL verification failed for Codex API; retrying with verify=False"
                    )
                    return await _request_codex(
                        DEFAULT_CODEX_URL,
                        headers,
                        wire_body,
                        verify=self._ssl_context(verify=False),
                        proxy=self.proxy,
                        on_content_delta=on_content_delta if emit_deltas else None,
                        on_thinking_delta=on_thinking_delta if emit_deltas else None,
                        on_tool_call_delta=on_tool_call_delta if emit_deltas else None,
                    )

            compact_threshold = resolve_compact_threshold(
                (provider_context.context_window_tokens if provider_context is not None else None),
                max_tokens,
            )
            if (
                self.supports_native_compaction(model)
                and replayed
                and sanitized_state is not None
                and compact_threshold is not None
                and responses_state_context_tokens(sanitized_state) >= compact_threshold
            ):
                stage = "codex_compaction"
                history_items = responses_state_items(sanitized_state) or []
                delta_items = input_items[len(history_items):]
                compact_body = {
                    **body,
                    "input": [*history_items, {"type": "compaction_trigger"}],
                }
                try:
                    compact_result = await _send(compact_body, emit_deltas=False)
                    compact_items = (
                        responses_state_items(compact_result.provider_state)
                        if compact_result.provider_state is not None
                        else None
                    )
                    if not compact_items or compact_items[-1].get("type") not in {
                        "compaction",
                        "compaction_summary",
                        "context_compaction",
                    }:
                        raise RuntimeError("Codex compaction returned no compaction item")
                    body["input"] = [
                        *_retained_compaction_messages(history_items),
                        *compact_items,
                        *delta_items,
                    ]
                    native_compaction_state = build_responses_compaction_state(
                        provider=self._responses_state_provider(),
                        model=_strip_model_prefix(model),
                        output_items=compact_items,
                    )
                    native_compaction_applied = True
                except Exception as compact_error:
                    if is_compaction_compatibility_error(compact_error):
                        self._native_compaction_available = False
                    logger.warning(
                        "Codex native compaction unavailable; continuing without it "
                        "(type={} status={} disabled={})",
                        type(compact_error).__name__,
                        getattr(compact_error, "status_code", None),
                        not self._native_compaction_available,
                    )

            stage = "codex_request"
            result = await _send(body, emit_deltas=True)
            result.provider_compaction_applied = (
                result.provider_compaction_applied or native_compaction_applied
            )
            if native_compaction_state is not None:
                result.provider_compaction_state = native_compaction_state
                result.provider_compaction_scope = "prior_context"
            return result
        except Exception as e:
            response = _codex_error_response(e)
            exc_type = "CodexHTTPError" if isinstance(e, _CodexHTTPError) else type(e).__name__
            logger.warning(
                "Codex API request failed: stage={} type={} kind={} retryable={} status={} "
                "error_type={} error_code={} retry_after={} summary={}",
                stage,
                exc_type,
                response.error_kind,
                response.error_should_retry,
                response.error_status_code,
                response.error_type,
                response.error_code,
                response.retry_after,
                _codex_log_summary(exc_type, response),
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
        provider_context: ProviderCallContext | None = None,
    ) -> LLMResponse:
        return await self._call_codex(
            messages,
            tools,
            model,
            max_tokens,
            reasoning_effort,
            tool_choice,
            provider_context=provider_context,
        )

    async def chat_with_context(
        self,
        *,
        provider_context: ProviderCallContext,
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.chat(
            **kwargs,
            provider_context=provider_context,
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
        provider_context: ProviderCallContext | None = None,
    ) -> LLMResponse:
        return await self._call_codex(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            on_content_delta=on_content_delta,
            on_thinking_delta=on_thinking_delta,
            on_tool_call_delta=on_tool_call_delta,
            provider_context=provider_context,
        )

    async def chat_stream_with_context(
        self,
        *,
        provider_context: ProviderCallContext,
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.chat_stream(
            **kwargs,
            provider_context=provider_context,
        )

    def get_default_model(self) -> str:
        return self.default_model

    @staticmethod
    def _responses_state_provider() -> str:
        return f"openai_codex:{DEFAULT_CODEX_URL.rstrip('/')}"

    def can_resume_conversation_state(
        self,
        state: ProviderConversationState,
        model: str | None = None,
    ) -> bool:
        return responses_state_matches(
            state,
            provider=self._responses_state_provider(),
            model=_strip_model_prefix(model or self.default_model),
        )

    def supports_native_compaction(self, model: str | None = None) -> bool:
        """Use the Codex backend's inline compaction trigger when needed."""
        _ = model
        return self._native_compaction_available


def _strip_model_prefix(model: str) -> str:
    if model.startswith("openai-codex/") or model.startswith("openai_codex/"):
        return model.split("/", 1)[1]
    return model


def _without_response_item_ids(
    request_body: dict[str, Any],
) -> dict[str, Any]:
    """Match Codex's default ``store=false`` request-item contract."""
    if request_body.get("store") is True:
        return request_body
    raw_input = request_body.get("input")
    if not isinstance(raw_input, list):
        return request_body

    input_items: list[object] = cast(list[object], raw_input)
    sanitized_input: list[object] = []
    for raw_item in input_items:
        if not isinstance(raw_item, dict):
            sanitized_input.append(raw_item)
            continue
        item = cast(dict[str, Any], raw_item)
        sanitized_input.append({key: value for key, value in item.items() if key != "id"})

    body = dict(request_body)
    body["input"] = sanitized_input
    return body


def _retained_compaction_messages(
    input_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Mirror Codex's bounded retention of user/developer/system messages."""
    retained_reversed: list[dict[str, Any]] = []
    remaining = _COMPACTION_RETAINED_CHAR_BUDGET
    for item in reversed(input_items):
        if item.get("type") not in {None, "message"} or item.get("role") not in {
            "user",
            "developer",
            "system",
        }:
            continue
        size = len(json.dumps(item, ensure_ascii=False))
        if size > remaining and retained_reversed:
            continue
        retained_reversed.append(item)
        remaining = max(0, remaining - size)
        if remaining == 0:
            break
    retained_reversed.reverse()
    return retained_reversed


def _build_reasoning_options(reasoning_effort: str | None) -> dict[str, str] | None:
    """Opt in to visible summaries without changing provider-default effort."""
    if reasoning_effort and reasoning_effort.lower() == "none":
        return {"effort": "none"}
    options = {"summary": "auto"}
    if reasoning_effort:
        options["effort"] = reasoning_effort
    return options


def _build_headers(
    account_id: str,
    token: str,
    *,
    session_routing_key: str | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": DEFAULT_ORIGINATOR,
        "User-Agent": "nanobot (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }
    if session_routing_key:
        headers["session-id"] = session_routing_key
    return headers


class _CodexHTTPError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        should_retry: bool | None = None,
        compaction_unsupported: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.error_type = error_type
        self.error_code = error_code
        self.should_retry = should_retry
        self.compaction_unsupported = compaction_unsupported


async def _request_codex(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    verify: ssl.SSLContext | bool,
    proxy: str | None = None,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> LLMResponse:
    idle_timeout_s = resolve_stream_idle_timeout_s()
    client_kwargs: dict[str, Any] = {"timeout": idle_timeout_s, "verify": verify}
    if proxy:
        client_kwargs["proxy"] = proxy
        client_kwargs["trust_env"] = False
    async with httpx.AsyncClient(**client_kwargs) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                text = await response.aread()
                raw = text.decode("utf-8", "ignore")
                retry_after = LLMProvider._extract_retry_after_from_headers(response.headers)
                error_type, error_code = LLMProvider._extract_error_type_code(raw)
                compaction_unsupported = response.status_code in {400, 404, 422} and any(
                    marker in raw.lower()
                    for marker in (
                        "context_management",
                        "compact_threshold",
                        "compaction_trigger",
                    )
                )
                raise _CodexHTTPError(
                    _friendly_error(response.status_code, raw),
                    status_code=response.status_code,
                    retry_after=retry_after,
                    error_type=error_type,
                    error_code=error_code,
                    should_retry=_should_retry_status(
                        response.status_code, error_type, error_code, raw
                    ),
                    compaction_unsupported=compaction_unsupported,
                )
            capture = ResponsesStreamCapture()
            (
                content,
                tool_calls,
                finish_reason,
                usage,
                reasoning_content,
            ) = await consume_sse_with_reasoning(
                response,
                on_content_delta=on_content_delta,
                on_tool_call_delta=on_tool_call_delta,
                on_reasoning_delta=on_thinking_delta,
                capture=capture,
            )
            result = LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                reasoning_content=reasoning_content,
            )
            if capture.completed and is_replayable_finish_reason(finish_reason):
                result.provider_state = build_responses_state(
                    provider=f"openai_codex:{url.rstrip('/')}",
                    model=str(body.get("model") or ""),
                    input_items=cast(list[dict[str, Any]], body.get("input") or []),
                    output_items=capture.output_items,
                    usage=usage,
                )
            return result


def _prompt_cache_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _friendly_error(status_code: int, raw: str) -> str:
    _ = raw
    if status_code == 429:
        return "ChatGPT usage quota exceeded or rate limit triggered. Please try again later."
    return f"HTTP {status_code}: Codex API request failed"


def _codex_error_response(exc: Exception) -> LLMResponse:
    """Convert Codex transport/API failures into actionable, retryable metadata."""
    exc_type = "CodexHTTPError" if isinstance(exc, _CodexHTTPError) else type(exc).__name__
    detail = str(exc).strip()

    status_code = getattr(exc, "status_code", None)
    error_kind: str | None = None
    default_detail: str | None = None
    should_retry: bool | None = getattr(exc, "should_retry", None)

    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
        error_kind = "timeout"
        default_detail = "timed out waiting for response"
        should_retry = True if should_retry is None else should_retry
    elif isinstance(exc, httpx.RemoteProtocolError):
        error_kind = "connection"
        default_detail = "network protocol error while reading response"
        should_retry = True if should_retry is None else should_retry
    elif isinstance(exc, (httpx.NetworkError, httpx.TransportError)):
        error_kind = "connection"
        default_detail = "network connection failed"
        should_retry = True if should_retry is None else should_retry
    elif isinstance(exc, _CodexHTTPError):
        error_kind = "http"
        default_detail = "HTTP request failed"

    if status_code is not None and should_retry is None:
        retry_content = (
            None if int(status_code) == 429 and isinstance(exc, _CodexHTTPError) else detail
        )
        should_retry = _should_retry_status(
            int(status_code),
            getattr(exc, "error_type", None),
            getattr(exc, "error_code", None),
            retry_content,
        )

    detail = detail or default_detail or "unexpected error"
    message = f"Error calling Codex ({exc_type}): {detail}"
    retry_after = getattr(exc, "retry_after", None) or LLMProvider._extract_retry_after(message)
    return LLMResponse(
        content=message,
        finish_reason="error",
        retry_after=retry_after,
        error_status_code=int(status_code) if status_code is not None else None,
        error_kind=error_kind,
        error_type=getattr(exc, "error_type", None),
        error_code=getattr(exc, "error_code", None),
        error_retry_after_s=retry_after,
        error_should_retry=should_retry,
    )


def _codex_log_summary(exc_type: str, response: LLMResponse) -> str:
    """Return a bounded diagnostic summary without request body or raw upstream payload."""
    if response.error_status_code is not None:
        parts = [f"HTTP {response.error_status_code}"]
        if response.error_type:
            parts.append(f"type={response.error_type}")
        if response.error_code:
            parts.append(f"code={response.error_code}")
        return " ".join(parts)

    kind = (response.error_kind or "").strip()
    if kind:
        return f"{exc_type} {kind}"

    return exc_type


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


def get_openai_codex_model_catalog(
    proxy: str | None = None,
) -> OAuthModelCatalogSnapshot:
    storage = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename)
    token = storage.load()
    account_id = getattr(token, "account_id", None)
    account_key = _catalog_account_key(account_id)
    cache_key = f"{storage.get_token_path()}\0{account_key}\0{proxy or ''}"
    return _OPENAI_CODEX_MODEL_CATALOG.get(cache_key=cache_key, proxy=proxy)


def invalidate_openai_codex_model_catalog() -> None:
    _OPENAI_CODEX_MODEL_CATALOG.invalidate()


def _fetch_openai_codex_models(proxy: str | None) -> tuple[ProviderModelSpec, ...]:
    token = get_codex_token(proxy=proxy)
    account_id = getattr(token, "account_id", None)
    if not isinstance(account_id, str) or not account_id:
        raise RuntimeError("OpenAI Codex OAuth token has no account ID")
    client_kwargs: dict[str, Any] = {"timeout": 10.0, "follow_redirects": False}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    with httpx.Client(**client_kwargs) as client:
        response = client.get(
            DEFAULT_OPENAI_CODEX_MODELS_URL,
            params={"client_version": OPENAI_CODEX_CATALOG_CLIENT_VERSION},
            headers={
                "Authorization": f"Bearer {token.access}",
                "chatgpt-account-id": account_id,
                "originator": DEFAULT_ORIGINATOR,
                "User-Agent": f"nanobot/{__version__} (python)",
                "accept": "application/json",
            },
        )
    response.raise_for_status()
    return _parse_openai_codex_models(response.json())


def _parse_openai_codex_models(payload: Any) -> tuple[ProviderModelSpec, ...]:
    rows = cast(dict[str, Any], payload).get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ()

    fallback_models = _oauth_fallback_models("openai_codex")
    fallback_by_id = {model.id.split("/", 1)[-1]: model for model in fallback_models}
    parsed: list[tuple[int, ProviderModelSpec]] = []
    seen: set[str] = set()
    for value in cast(list[object], rows):
        if not isinstance(value, dict):
            continue
        row = cast(dict[str, Any], value)
        wire_id = _catalog_first_text(row, "slug", "id")
        if not wire_id or wire_id in seen or row.get("visibility") in {"hide", "none"}:
            continue
        seen.add(wire_id)
        fallback = fallback_by_id.get(wire_id)
        priority = row.get("priority")
        parsed.append(
            (
                priority if isinstance(priority, int) and not isinstance(priority, bool) else 2**31,
                ProviderModelSpec(
                    id=f"openai-codex/{wire_id}",
                    label=(
                        _catalog_first_text(row, "display_name", "name")
                        or (fallback.label if fallback is not None else wire_id)
                    ),
                    description=(
                        _catalog_first_text(row, "description")
                        or (fallback.description if fallback is not None else "")
                    ),
                    owned_by="OpenAI Codex",
                    context_window=(
                        _catalog_positive_int(row, "context_window")
                        or (fallback.context_window if fallback is not None else None)
                    ),
                    reasoning_efforts=(
                        _catalog_reasoning_efforts(row.get("supported_reasoning_levels"))
                        or (fallback.reasoning_efforts if fallback is not None else ())
                    ),
                ),
            )
        )
    parsed.sort(key=lambda item: item[0])
    return tuple(model for _, model in parsed)


def _oauth_fallback_models(provider_name: str) -> tuple[ProviderModelSpec, ...]:
    spec = find_by_name(provider_name)
    assert spec is not None
    return spec.builtin_models


def _catalog_account_key(account_id: object) -> str:
    value = account_id if isinstance(account_id, str) else ""
    return hashlib.sha256(value.encode()).hexdigest()[:16] if value else "anonymous"


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


_OPENAI_CODEX_MODEL_CATALOG = OAuthModelCatalog(
    fallback_models=_oauth_fallback_models("openai_codex"),
    fetch=_fetch_openai_codex_models,
)
