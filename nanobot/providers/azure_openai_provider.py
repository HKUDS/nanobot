"""Azure OpenAI provider using the OpenAI SDK Responses API.

Uses ``AsyncOpenAI`` pointed at ``https://{endpoint}/openai/v1/`` which
routes to the Responses API (``/responses``).  Reuses shared conversion
helpers from :mod:`nanobot.providers.openai_responses`.

Authentication
--------------
Two modes are supported, selected automatically:

1. **Static API key** — when ``api_key`` is non-empty it is sent as the
   ``api-key`` / ``Authorization: Bearer`` header (existing behavior).
2. **Microsoft Entra ID (AAD)** — when ``api_key`` is empty the provider
   falls back to :class:`azure.identity.aio.DefaultAzureCredential` and
   acquires a bearer token scoped to
   ``https://cognitiveservices.azure.com/.default``.  ``azure-identity``
   is an optional dependency installed via ``nanobot plugins enable azure``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

from loguru import logger
from openai import AsyncOpenAI

from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCallContext,
    ProviderConversationState,
)
from nanobot.providers.openai_responses import (
    ResponsesStreamCapture,
    build_responses_state,
    consume_sdk_stream,
    convert_tools,
    is_compaction_compatibility_error,
    is_replayable_finish_reason,
    parse_response_output,
    prepare_responses_input,
    resolve_compact_threshold,
    responses_state_matches,
)

_AZURE_OPENAI_SCOPE = "https://cognitiveservices.azure.com/.default"


class _AzureTokenProvider:
    """Async bearer-token callback for AAD authentication.

    Thin wrapper around :class:`azure.identity.aio.DefaultAzureCredential`
    that exposes itself as an async callable returning a fresh bearer
    token.  The Azure SDK's own MSAL-backed token cache already returns
    valid tokens without network calls, so no extra caching is layered on
    top here.

    Raises ``RuntimeError`` with a clear install hint if
    ``azure-identity`` is not installed.
    """

    def __init__(self, scope: str = _AZURE_OPENAI_SCOPE) -> None:
        try:
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:
            raise RuntimeError(
                "Azure OpenAI AAD authentication requires the 'azure-identity' package. "
                "Run: nanobot plugins enable azure"
            ) from exc

        self._scope = scope
        self._credential = DefaultAzureCredential()

    async def __call__(self) -> str:
        """Return a bearer token for the configured scope."""
        access_token = await self._credential.get_token(self._scope)
        return access_token.token

    async def aclose(self) -> None:
        """Release credential resources.  Safe to call multiple times."""
        close = getattr(self._credential, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI provider backed by the Responses API.

    Features:
    - Uses the OpenAI Python SDK (``AsyncOpenAI``) with
      ``base_url = {endpoint}/openai/v1/``
    - Calls ``client.responses.create()`` (Responses API)
    - Reuses shared message/tool/SSE conversion from
      ``openai_responses``
    - Falls back to :class:`DefaultAzureCredential` (AAD) when ``api_key``
      is empty.  See module docstring for details.
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        default_model: str = "gpt-5.2-chat",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._native_compaction_available = True

        if not api_base:
            raise ValueError("Azure OpenAI api_base is required")

        # Normalise: ensure trailing slash
        if not api_base.endswith("/"):
            api_base += "/"
        self.api_base = api_base

        # Select auth mode.  A truthy api_key wins; otherwise fall back to
        # AAD via DefaultAzureCredential.  The OpenAI SDK accepts an async
        # callable as ``api_key`` and invokes it per request, using the
        # returned string as the bearer token.
        self._token_provider: _AzureTokenProvider | None = None
        client_api_key: str | Callable[[], Awaitable[str]]
        if api_key:
            client_api_key = api_key
        else:
            self._token_provider = _AzureTokenProvider()
            client_api_key = self._token_provider

        # SDK client targeting the Azure Responses API endpoint
        base_url = f"{api_base.rstrip('/')}/openai/v1/"
        self._client = AsyncOpenAI(
            api_key=client_api_key,
            base_url=base_url,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
            max_retries=0,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _supports_temperature(
        deployment_name: str,
        reasoning_effort: str | None = None,
    ) -> bool:
        """Return True when temperature is likely supported for this deployment."""
        if reasoning_effort and reasoning_effort.lower() != "none":
            return False
        name = deployment_name.lower()
        return not any(token in name for token in ("gpt-5", "o1", "o3", "o4"))

    def _responses_state_provider(self) -> str:
        return f"azure_openai:{str(self.api_base).rstrip('/')}"

    def can_resume_conversation_state(
        self,
        state: ProviderConversationState,
        model: str | None = None,
    ) -> bool:
        return responses_state_matches(
            state,
            provider=self._responses_state_provider(),
            model=model or self.default_model,
        )

    def supports_native_compaction(self, model: str | None = None) -> bool:
        """Azure's native Responses endpoint accepts context management."""
        _ = model
        return self._native_compaction_available

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        provider_context: ProviderCallContext | None = None,
    ) -> dict[str, Any]:
        """Build the Responses API request body from Chat-Completions-style args."""
        deployment = model or self.default_model
        sanitized_messages = self._sanitize_empty_content(messages)
        sanitized_state = (
            provider_context.conversation_state
            if provider_context is not None
            else None
        )
        if sanitized_state is not None:
            sanitized_state = sanitized_state.with_pending_messages(
                self._sanitize_empty_content(sanitized_state.pending_messages)
            )
        instructions, input_items, replayed = prepare_responses_input(
            sanitized_messages,
            state=sanitized_state,
            provider=self._responses_state_provider(),
            model=deployment,
        )

        body: dict[str, Any] = {
            "model": deployment,
            "instructions": instructions or None,
            "input": input_items,
            "max_output_tokens": max(1, max_tokens),
            "store": False,
            "stream": False,
        }
        compact_threshold = resolve_compact_threshold(
            (
                provider_context.context_window_tokens
                if provider_context is not None
                else None
            ),
            max_tokens,
        )
        if self.supports_native_compaction(deployment) and compact_threshold is not None:
            body["context_management"] = [{
                "type": "compaction",
                "compact_threshold": compact_threshold,
            }]

        if self._supports_temperature(deployment, reasoning_effort):
            body["temperature"] = temperature

        if not self._supports_temperature(deployment, reasoning_effort):
            body["include"] = ["reasoning.encrypted_content"]
        if reasoning_effort and reasoning_effort.lower() != "none":
            body["reasoning"] = {"effort": reasoning_effort}
        if replayed and "gpt-5.6" in deployment.lower():
            body.setdefault("reasoning", {})["context"] = "all_turns"

        if tools:
            body["tools"] = convert_tools(tools)
            body["tool_choice"] = tool_choice or "auto"

        return body

    async def _create_response_with_compaction_fallback(
        self,
        body: dict[str, Any],
    ) -> Any:
        """Retry once without server compaction when Azure rejects the option."""
        try:
            return cast(Any, await self._client.responses.create(**body))
        except Exception as exc:
            if (
                "context_management" not in body
                or not is_compaction_compatibility_error(exc)
            ):
                raise
            self._native_compaction_available = False
            body.pop("context_management", None)
            logger.warning(
                "Azure Responses server compaction unsupported; disabled for this provider "
                "instance (status={})",
                getattr(exc, "status_code", None),
            )
            return cast(Any, await self._client.responses.create(**body))

    @staticmethod
    def _handle_error(e: Exception) -> LLMResponse:
        response = getattr(e, "response", None)
        body = getattr(e, "body", None) or getattr(response, "text", None)
        body_text = str(body).strip() if body is not None else ""
        msg = f"Error: {body_text[:500]}" if body_text else f"Error calling Azure OpenAI: {e}"
        headers = getattr(response, "headers", None)
        retry_after = LLMProvider._extract_retry_after_from_headers(headers)
        if retry_after is None:
            retry_after = LLMProvider._extract_retry_after(msg)
        status_code = getattr(e, "status_code", None)
        if status_code is None and response is not None:
            status_code = getattr(response, "status_code", None)
        error_type, error_code = LLMProvider._extract_error_type_code(body)
        should_retry: bool | None = None
        if headers is not None:
            raw_should_retry = headers.get("x-should-retry")
            if isinstance(raw_should_retry, str):
                lowered = raw_should_retry.strip().lower()
                if lowered == "true":
                    should_retry = True
                elif lowered == "false":
                    should_retry = False
        error_name = type(e).__name__.lower()
        error_kind = (
            "timeout"
            if "timeout" in error_name
            else "connection"
            if "connection" in error_name
            else None
        )
        return LLMResponse(
            content=msg,
            finish_reason="error",
            retry_after=retry_after,
            error_status_code=int(status_code) if status_code is not None else None,
            error_kind=error_kind,
            error_type=error_type,
            error_code=error_code,
            error_retry_after_s=retry_after,
            error_should_retry=should_retry,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        body = self._build_body(
            messages, tools, model, max_tokens, temperature,
            reasoning_effort, tool_choice,
            provider_context,
        )
        try:
            response = await self._create_response_with_compaction_fallback(body)
            return parse_response_output(
                response,
                state_provider=self._responses_state_provider(),
                state_model=str(body["model"]),
                state_input_items=cast(list[dict[str, Any]], body["input"]),
            )
        except Exception as e:
            return self._handle_error(e)

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
        _ = on_thinking_delta
        body = self._build_body(
            messages, tools, model, max_tokens, temperature,
            reasoning_effort, tool_choice,
            provider_context,
        )
        body["stream"] = True

        try:
            stream = await self._create_response_with_compaction_fallback(body)
            capture = ResponsesStreamCapture()
            content, tool_calls, finish_reason, usage, reasoning_content = (
                await consume_sdk_stream(
                    stream,
                    on_content_delta,
                    on_tool_call_delta,
                    capture=capture,
                )
            )
            result = LLMResponse(
                content=content or None,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                reasoning_content=reasoning_content,
            )
            if capture.completed and is_replayable_finish_reason(finish_reason):
                result.provider_state = build_responses_state(
                    provider=self._responses_state_provider(),
                    model=str(body["model"]),
                    input_items=cast(list[dict[str, Any]], body["input"]),
                    output_items=capture.output_items,
                    usage=usage,
                )
            return result
        except Exception as e:
            return self._handle_error(e)

    def get_default_model(self) -> str:
        return self.default_model
