"""Provider-like model router with bounded cross-model failover."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.config.schema import FailoverConfig
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


@dataclass(frozen=True)
class ModelCandidate:
    """Lazy provider candidate used by ModelRouter."""

    model: str
    provider_name: str | None
    provider_factory: Callable[[], LLMProvider]

    @property
    def key(self) -> tuple[str | None, str]:
        return self.provider_name, self.model

    @property
    def label(self) -> str:
        provider = self.provider_name or "unknown"
        return f"{provider}/{self.model}"


class ModelRouter(LLMProvider):
    """Route to fallback models after a provider returns a final retry error."""

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
        primary_provider_name: str | None,
        fallback_candidates: list[ModelCandidate],
        failover: FailoverConfig,
    ) -> None:
        super().__init__(
            api_key=getattr(primary_provider, "api_key", None),
            api_base=getattr(primary_provider, "api_base", None),
        )
        self.primary_provider = primary_provider
        self.primary_model = primary_model
        self.primary_provider_name = primary_provider_name
        self.fallback_candidates = list(fallback_candidates)
        self.failover = failover
        self.generation = getattr(primary_provider, "generation", GenerationSettings())
        self._provider_cache: dict[tuple[str | None, str], LLMProvider] = {
            (primary_provider_name, primary_model): primary_provider
        }
        self._cooldowns: dict[tuple[str | None, str], float] = {}

    def get_default_model(self) -> str:
        return self.primary_model

    async def chat(self, **kwargs: Any) -> LLMResponse:
        return await self.primary_provider.chat(**kwargs)

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        return await self.primary_provider.chat_stream(**kwargs)

    def fallback_chain(self) -> tuple[str, ...]:
        return tuple(candidate.model for candidate in self.fallback_candidates)

    def _candidate_chain(self) -> list[ModelCandidate]:
        switch_limit = self.failover.max_switches_per_turn
        fallbacks = (
            self.fallback_candidates
            if switch_limit == 0
            else self.fallback_candidates[:switch_limit]
        )
        return [
            ModelCandidate(
                model=self.primary_model,
                provider_name=self.primary_provider_name,
                provider_factory=lambda: self.primary_provider,
            ),
            *fallbacks,
        ]

    def _is_in_cooldown(self, candidate: ModelCandidate, now: float) -> bool:
        until = self._cooldowns.get(candidate.key)
        return until is not None and until > now

    def _mark_cooldown(self, candidate: ModelCandidate) -> None:
        if self.failover.cooldown_seconds <= 0:
            return
        self._cooldowns[candidate.key] = time.monotonic() + self.failover.cooldown_seconds

    def _get_provider(self, candidate: ModelCandidate) -> LLMProvider:
        provider = self._provider_cache.get(candidate.key)
        if provider is not None:
            return provider
        provider = candidate.provider_factory()
        self._provider_cache[candidate.key] = provider
        return provider

    def _factory_error_response(self, candidate: ModelCandidate, exc: Exception) -> LLMResponse:
        logger.warning(
            "Failed to configure fallback candidate provider={} model={}: {}",
            candidate.provider_name,
            candidate.model,
            exc,
        )
        return LLMResponse(
            content=f"Error configuring fallback model {candidate.model}: {exc}",
            finish_reason="error",
            error_kind="configuration",
            error_should_retry=False,
        )

    def _is_quota_error(self, response: LLMResponse) -> bool:
        tokens = {
            self._normalize_error_token(response.error_type),
            self._normalize_error_token(response.error_code),
        }
        if any(token in self._NON_RETRYABLE_429_ERROR_TOKENS for token in tokens if token):
            return True
        content = (response.content or "").lower()
        return any(marker in content for marker in self._QUOTA_MARKERS)

    def _is_blocked_error(self, response: LLMResponse) -> bool:
        status = response.error_status_code
        if status is not None and int(status) in self._BLOCKED_STATUS_CODES:
            return True
        if response.finish_reason in {"refusal", "content_filter"}:
            return True
        content = (response.content or "").lower()
        return any(marker in content for marker in self._NON_FAILOVER_MARKERS)

    def _should_failover(self, response: LLMResponse) -> bool:
        if response.finish_reason != "error":
            return False
        if self._is_blocked_error(response):
            return False
        if self._is_quota_error(response) and not self.failover.failover_on_quota:
            return False
        return self._is_transient_response(response)

    def _log_failover(
        self,
        *,
        candidate: ModelCandidate,
        response: LLMResponse,
        next_candidate: ModelCandidate | None,
    ) -> None:
        status = response.error_status_code
        kind = response.error_kind or response.error_type or response.error_code or "unknown"
        if next_candidate is None:
            logger.warning(
                "LLM failover exhausted provider={} model={} status={} kind={}",
                candidate.provider_name,
                candidate.model,
                status,
                kind,
            )
            return
        logger.warning(
            "LLM failover provider={} model={} status={} kind={} next_provider={} next_model={} cooldown={}",
            candidate.provider_name,
            candidate.model,
            status,
            kind,
            next_candidate.provider_name,
            next_candidate.model,
            self.failover.cooldown_seconds > 0,
        )

    async def _route(
        self,
        call: Callable[[LLMProvider, str, Callable[[str], Awaitable[None]] | None], Awaitable[LLMResponse]],
        *,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        if not self.failover.enabled or not self.fallback_candidates:
            return await call(self.primary_provider, self.primary_model, on_content_delta)

        chain = self._candidate_chain()
        last_response: LLMResponse | None = None
        now = time.monotonic()
        for index, candidate in enumerate(chain):
            if index > 0 and self._is_in_cooldown(candidate, now):
                logger.info(
                    "Skipping LLM fallback in cooldown provider={} model={}",
                    candidate.provider_name,
                    candidate.model,
                )
                continue
            try:
                provider = self._get_provider(candidate)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                response = self._factory_error_response(candidate, exc)
            else:
                response = await call(provider, candidate.model, on_content_delta)

            if response.finish_reason != "error":
                if index > 0:
                    logger.info(
                        "LLM failover selected provider={} model={}",
                        candidate.provider_name,
                        candidate.model,
                    )
                return response

            last_response = response
            if not self._should_failover(response):
                return response

            self._mark_cooldown(candidate)
            next_candidate = next(
                (
                    item for item in chain[index + 1:]
                    if not self._is_in_cooldown(item, time.monotonic())
                ),
                None,
            )
            self._log_failover(
                candidate=candidate,
                response=response,
                next_candidate=next_candidate,
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
        async def call(provider: LLMProvider, candidate_model: str, _delta: Any) -> LLMResponse:
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
