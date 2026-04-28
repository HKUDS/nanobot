"""Provider-like failover router used after provider-local retry is exhausted."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


@dataclass(frozen=True)
class ModelCandidate:
    """A lazily resolved model/provider candidate."""

    label: str
    resolver: Callable[[], tuple[LLMProvider, str]]


class ModelRouter(LLMProvider):
    """Try fallback model candidates for eligible transient final errors."""

    supports_progress_deltas = False

    _BLOCKED_STATUS_CODES = frozenset({400, 401, 403, 404, 422})
    _QUOTA_MARKERS = (
        "insufficient_quota",
        "insufficient quota",
        "quota exceeded",
        "quota_exceeded",
        "quota exhausted",
        "quota_exhausted",
        "billing hard limit",
        "billing_hard_limit_reached",
        "billing not active",
        "insufficient balance",
        "insufficient_balance",
        "credit balance too low",
        "payment required",
        "out of credits",
        "out of quota",
        "exceeded your current quota",
    )
    _NON_FAILOVER_MARKERS = (
        "context length",
        "context_length",
        "maximum context",
        "max context",
        "token budget",
        "too many tokens",
        "schema",
        "invalid request",
        "invalid_request",
        "invalid parameter",
        "invalid_parameter",
        "unsupported",
        "unauthorized",
        "authentication",
        "permission",
        "forbidden",
        "refusal",
        "content policy",
        "content_filter",
        "policy violation",
        "safety",
    )

    def __init__(
        self,
        *,
        primary_provider: LLMProvider,
        primary_model: str,
        fallback_candidates: list[ModelCandidate],
        per_candidate_timeout_s: float | None = None,
    ) -> None:
        super().__init__(
            api_key=getattr(primary_provider, "api_key", None),
            api_base=getattr(primary_provider, "api_base", None),
        )
        self.primary_provider = primary_provider
        self.primary_model = primary_model
        self.fallback_candidates = list(fallback_candidates)
        self.per_candidate_timeout_s = per_candidate_timeout_s
        self.generation = getattr(primary_provider, "generation", GenerationSettings())

    def get_default_model(self) -> str:
        return self.primary_model

    async def chat(self, **kwargs: Any) -> LLMResponse:
        return await self.primary_provider.chat(**kwargs)

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        return await self.primary_provider.chat_stream(**kwargs)

    @classmethod
    def _is_quota_error(cls, response: LLMResponse) -> bool:
        tokens = {
            cls._normalize_error_token(response.error_type),
            cls._normalize_error_token(response.error_code),
        }
        if any(token in cls._NON_RETRYABLE_429_ERROR_TOKENS for token in tokens if token):
            return True
        content = (response.content or "").lower()
        return any(marker in content for marker in cls._QUOTA_MARKERS)

    @classmethod
    def _is_blocked_error(cls, response: LLMResponse) -> bool:
        status = response.error_status_code
        if status is not None and int(status) in cls._BLOCKED_STATUS_CODES:
            return True
        if response.finish_reason in {"refusal", "content_filter"}:
            return True
        content = (response.content or "").lower()
        return any(marker in content for marker in cls._NON_FAILOVER_MARKERS)

    @classmethod
    def _should_failover(cls, response: LLMResponse) -> bool:
        if response.finish_reason != "error":
            return False
        if cls._is_blocked_error(response):
            return False
        if cls._is_quota_error(response):
            return False
        return cls._is_transient_response(response)

    async def _with_timeout(self, coro: Awaitable[LLMResponse]) -> LLMResponse:
        timeout_s = self.per_candidate_timeout_s
        if timeout_s is None:
            return await coro
        try:
            return await asyncio.wait_for(coro, timeout=timeout_s)
        except asyncio.TimeoutError:
            return LLMResponse(
                content=f"Error calling LLM: timed out after {timeout_s:g}s",
                finish_reason="error",
                error_kind="timeout",
            )

    @staticmethod
    def _resolver_error(candidate: ModelCandidate, exc: Exception) -> LLMResponse:
        logger.warning("Failed to resolve fallback model {}: {}", candidate.label, exc)
        return LLMResponse(
            content=f"Error configuring fallback model {candidate.label}: {exc}",
            finish_reason="error",
            error_kind="configuration",
            error_should_retry=False,
        )

    def _candidate_chain(self) -> list[ModelCandidate]:
        return [
            ModelCandidate(
                label=self.primary_model,
                resolver=lambda: (self.primary_provider, self.primary_model),
            ),
            *self.fallback_candidates,
        ]

    async def _route(
        self,
        call: Callable[[LLMProvider, str, Callable[[str], Awaitable[None]] | None], Awaitable[LLMResponse]],
        *,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        last_response: LLMResponse | None = None
        chain = self._candidate_chain()
        for index, candidate in enumerate(chain):
            try:
                provider, model = candidate.resolver()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                response = self._resolver_error(candidate, exc)
            else:
                response = await self._with_timeout(call(provider, model, on_content_delta))

            if response.finish_reason != "error":
                if index > 0:
                    logger.info("LLM failover selected model={}", candidate.label)
                return response

            last_response = response
            if not self._should_failover(response):
                return response
            if index + 1 >= len(chain):
                logger.warning("LLM failover exhausted after model={}", candidate.label)
                return response
            logger.warning(
                "LLM failover model={} next_model={} status={} kind={}",
                candidate.label,
                chain[index + 1].label,
                response.error_status_code,
                response.error_kind or response.error_type or response.error_code or "unknown",
            )

        return last_response or LLMResponse(
            content="No available fallback model candidate.",
            finish_reason="error",
            error_kind="configuration",
            error_should_retry=False,
        )

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: object = LLMProvider._SENTINEL,
        temperature: object = LLMProvider._SENTINEL,
        reasoning_effort: object = LLMProvider._SENTINEL,
        tool_choice: str | dict[str, Any] | None = None,
        retry_mode: str = "standard",
        on_retry_wait: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        async def call(
            provider: LLMProvider,
            candidate_model: str,
            _delta: Callable[[str], Awaitable[None]] | None,
        ) -> LLMResponse:
            return await provider.chat_with_retry(
                messages=messages,
                tools=tools,
                model=candidate_model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
                retry_mode=retry_mode,
                on_retry_wait=on_retry_wait,
            )

        return await self._route(call)

    async def chat_stream_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: object = LLMProvider._SENTINEL,
        temperature: object = LLMProvider._SENTINEL,
        reasoning_effort: object = LLMProvider._SENTINEL,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        retry_mode: str = "standard",
        on_retry_wait: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        async def call(
            provider: LLMProvider,
            candidate_model: str,
            external_delta: Callable[[str], Awaitable[None]] | None,
        ) -> LLMResponse:
            buffered: list[str] = []

            async def buffer_delta(delta: str) -> None:
                buffered.append(delta)

            response = await provider.chat_stream_with_retry(
                messages=messages,
                tools=tools,
                model=candidate_model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
                on_content_delta=buffer_delta if external_delta else None,
                retry_mode=retry_mode,
                on_retry_wait=on_retry_wait,
            )
            if response.finish_reason != "error" and external_delta:
                for delta in buffered:
                    await external_delta(delta)
            return response

        return await self._route(call, on_content_delta=on_content_delta)
