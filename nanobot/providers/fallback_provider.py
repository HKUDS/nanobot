"""Provider wrapper that transparently fails over to fallback models on error."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Hashable
from enum import Enum, auto
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse

# Circuit breaker tuned to match OpenAICompatProvider's Responses API breaker.
_PRIMARY_FAILURE_THRESHOLD = 3
_PRIMARY_COOLDOWN_S = 60
_MISSING = object()
_FALLBACK_ERROR_KINDS = frozenset({
    "timeout",
    "connection",
    "server_error",
    "rate_limit",
    "overloaded",
})
_NON_FALLBACK_ERROR_KINDS = frozenset({
    "content_filter",
    "refusal",
    "context_length",
    "invalid_request",
})
_PROVIDER_DOMAIN_ERROR_KINDS = frozenset({
    "authentication",
    "auth",
    "permission",
})
_PROVIDER_DOMAIN_ERROR_TOKENS = (
    "authentication_error",
    "invalid_api_key",
    "incorrect_api_key",
    "invalid_token",
    "expired_token",
    "unauthorized",
    "permission_denied",
    "account_deactivated",
    "organization_deactivated",
)
_MODEL_ERROR_TOKENS = (
    "model_not_found",
    "model not found",
    "model_not_available",
    "model unavailable",
    "model_disabled",
    "model_not_supported",
    "unsupported_model",
    "model_permission",
    "model_access",
)
_FALLBACK_ERROR_TOKENS = (
    "rate_limit",
    "rate limit",
    "too_many_requests",
    "too many requests",
    "overloaded",
    "server_error",
    "server error",
    "temporarily unavailable",
    "timeout",
    "timed out",
    "connection",
    "empty",  # API returned empty choices (e.g. DeepSeek peak hours), transient
    "insufficient_quota",
    "insufficient quota",
    "quota_exceeded",
    "quota exceeded",
    "quota_exhausted",
    "quota exhausted",
    "billing_hard_limit",
    "insufficient_balance",
    "balance",
    "out of credits",
)


class FailoverDecision(Enum):
    """How failover should proceed after one candidate fails."""

    STOP = auto()
    NEXT_CANDIDATE = auto()
    NEXT_PROVIDER_DOMAIN = auto()


class FallbackProvider(LLMProvider):
    """Wrap a primary provider and transparently failover to fallback models.

    When the primary model returns a fallbackable error before content has been
    streamed, the wrapper tries each fallback model in order. Streamed timeout
    errors are the recovery exception: the caller may close the current stream
    segment, then the wrapper continues failover with later deltas in a new
    segment. Each fallback model may reside on a different provider — a factory
    callable creates the underlying provider on-the-fly.

    Key design:
    - Failover decisions and failed-domain skips are request-scoped.
    - Skipped when content was already streamed to avoid duplicate output,
      except timeout recovery can resume in a new stream segment.
    - Recursive failover is prevented by the factory returning plain providers.
    - Primary health and its tripped failure domain persist in the circuit
      breaker to avoid wasting requests on a known-bad endpoint or account.
    """

    supports_stream_recover_callback = True

    def __init__(
        self,
        primary: LLMProvider,
        fallback_presets: list[Any],
        provider_factory: Callable[[Any], LLMProvider],
        *,
        primary_failure_domain: Hashable | None = None,
        fallback_failure_domains: list[Hashable | None] | None = None,
    ):
        if (
            fallback_failure_domains is not None
            and len(fallback_failure_domains) != len(fallback_presets)
        ):
            raise ValueError("fallback_failure_domains must align with fallback_presets")
        self._primary = primary
        self._fallback_presets = list(fallback_presets)
        self._provider_factory = provider_factory
        self._primary_failure_domain = primary_failure_domain
        self._fallback_failure_domains = (
            list(fallback_failure_domains)
            if fallback_failure_domains is not None
            else [None] * len(fallback_presets)
        )
        self._has_fallbacks = bool(fallback_presets)
        self._primary_failures = 0
        self._primary_tripped_at: float | None = None
        self._primary_tripped_domain: Hashable | None = None

    @property
    def generation(self):
        return self._primary.generation

    @generation.setter
    def generation(self, value):
        self._primary.generation = value

    def get_default_model(self) -> str:
        return self._primary.get_default_model()

    @property
    def supports_progress_deltas(self) -> bool:
        return bool(getattr(self._primary, "supports_progress_deltas", False))

    def _primary_available(self) -> bool:
        """Return True if the primary provider is not currently tripped."""
        if self._primary_tripped_at is None:
            return True
        if time.monotonic() - self._primary_tripped_at >= _PRIMARY_COOLDOWN_S:
            # Half-open: allow one probe attempt.
            return True
        return False

    async def chat(self, **kwargs: Any) -> LLMResponse:
        if not self._has_fallbacks:
            return await self._primary.chat(**kwargs)
        return await self._try_with_fallback(
            lambda p, kw: p.chat(**kw), kwargs, has_streamed=None
        )

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        on_stream_recover = kwargs.pop("on_stream_recover", None)
        if not self._has_fallbacks:
            return await self._primary.chat_stream(**kwargs)

        has_streamed: list[bool] = [False]
        original_delta = kwargs.get("on_content_delta")

        async def _tracking_delta(text: str) -> None:
            if text:
                has_streamed[0] = True
            if original_delta:
                await original_delta(text)

        kwargs["on_content_delta"] = _tracking_delta
        return await self._try_with_fallback(
            lambda p, kw: p.chat_stream(**kw),
            kwargs,
            has_streamed=has_streamed,
            on_stream_recover=on_stream_recover,
        )

    async def _try_with_fallback(
        self,
        call: Callable[[LLMProvider, dict[str, Any]], Awaitable[LLMResponse]],
        kwargs: dict[str, Any],
        has_streamed: list[bool] | None,
        on_stream_recover: Callable[[], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        primary_model = kwargs.get("model") or self._primary.get_default_model()
        primary_was_attempted = False
        primary_error = "unknown error"
        last_response: LLMResponse | None = None
        last_attempted_model = primary_model
        blocked_domains: set[Hashable] = set()

        if self._primary_available():
            primary_was_attempted = True
            response = await call(self._primary, kwargs)
            if response.finish_reason != "error":
                self._primary_failures = 0
                self._primary_tripped_at = None
                self._primary_tripped_domain = None
                return response
            primary_error = (response.content or primary_error)[:120]
            last_response = response

            if has_streamed is not None and has_streamed[0]:
                is_timeout = (response.error_kind or "").lower() == "timeout"
                if is_timeout:
                    logger.warning(
                        "Primary model '{}' stream stalled after content was emitted; "
                        "attempting failover anyway",
                        primary_model,
                    )
                    has_streamed[0] = False
                    if on_stream_recover:
                        await on_stream_recover()
                    else:
                        kwargs["on_content_delta"] = None
                else:
                    logger.warning(
                        "Primary model error but content already streamed; skipping failover"
                    )
                    return response

            decision = self._failover_decision(response)
            if decision is FailoverDecision.STOP:
                logger.warning(
                    "Primary model '{}' returned non-fallbackable error: {}",
                    primary_model,
                    (response.content or "")[:120],
                )
                return response
            if (
                decision is FailoverDecision.NEXT_PROVIDER_DOMAIN
                and self._primary_failure_domain is not None
            ):
                blocked_domains.add(self._primary_failure_domain)

            self._primary_failures += 1
            if self._primary_failures >= _PRIMARY_FAILURE_THRESHOLD:
                self._primary_tripped_at = time.monotonic()
                self._primary_tripped_domain = (
                    self._primary_failure_domain
                    if decision is FailoverDecision.NEXT_PROVIDER_DOMAIN
                    else None
                )
                logger.warning(
                    "Primary model '{}' circuit open after {} consecutive failures",
                    primary_model, self._primary_failures,
                )
        else:
            logger.debug("Primary model '{}' circuit open; skipping", primary_model)
            if self._primary_tripped_domain is not None:
                blocked_domains.add(self._primary_tripped_domain)

        primary_skipped = not primary_was_attempted
        attempted_fallbacks = 0
        for idx, fallback in enumerate(self._fallback_presets):
            fallback_model = fallback.model
            failure_domain = self._fallback_failure_domains[idx]
            if failure_domain is not None and failure_domain in blocked_domains:
                logger.info(
                    "Skipping fallback '{}' in a provider failure domain that already failed",
                    fallback_model,
                )
                continue
            if has_streamed is not None and has_streamed[0]:
                is_timeout = (
                    last_response is not None
                    and (last_response.error_kind or "").lower() == "timeout"
                )
                if is_timeout and on_stream_recover:
                    logger.warning(
                        "Fallback model '{}' stream stalled after content was emitted; "
                        "starting a new stream segment and trying next fallback",
                        last_attempted_model,
                    )
                    has_streamed[0] = False
                    await on_stream_recover()
                else:
                    break
            if attempted_fallbacks == 0 and primary_skipped:
                logger.info(
                    "Primary model '{}' circuit open, trying fallback '{}'",
                    primary_model, fallback_model,
                )
            elif attempted_fallbacks == 0:
                logger.info(
                    "Primary model '{}' failed: {}; trying fallback '{}'",
                    primary_model, primary_error, fallback_model,
                )
            else:
                logger.info(
                    "Fallback '{}' failed, trying next fallback '{}'",
                    last_attempted_model, fallback_model,
                )
            try:
                fallback_provider = self._provider_factory(fallback)
            except Exception as exc:
                logger.warning(
                    "Failed to create provider for fallback '{}': {}", fallback_model, exc
                )
                continue

            attempted_fallbacks += 1
            last_attempted_model = fallback_model
            original_values = {
                name: kwargs.get(name, _MISSING)
                for name in ("model", "max_tokens", "temperature", "reasoning_effort")
            }
            kwargs["model"] = fallback_model
            kwargs["max_tokens"] = fallback.max_tokens
            kwargs["temperature"] = fallback.temperature
            if fallback.reasoning_effort is None:
                kwargs.pop("reasoning_effort", None)
            else:
                kwargs["reasoning_effort"] = fallback.reasoning_effort
            try:
                fallback_response = await call(fallback_provider, kwargs)
            finally:
                for name, value in original_values.items():
                    if value is _MISSING:
                        kwargs.pop(name, None)
                    else:
                        kwargs[name] = value

            if fallback_response.finish_reason != "error":
                logger.info(
                    "Fallback '{}' succeeded after primary '{}' failed",
                    fallback_model, primary_model,
                )
                return fallback_response

            last_response = fallback_response
            logger.warning(
                "Fallback '{}' also failed: {}",
                fallback_model,
                (fallback_response.content or "")[:120],
            )
            decision = self._failover_decision(fallback_response)
            if decision is FailoverDecision.STOP:
                logger.warning(
                    "Fallback '{}' returned non-fallbackable error; stopping failover",
                    fallback_model,
                )
                return fallback_response
            if (
                decision is FailoverDecision.NEXT_PROVIDER_DOMAIN
                and failure_domain is not None
            ):
                blocked_domains.add(failure_domain)

        logger.warning(
            "All {} fallback model(s) failed",
            len(self._fallback_presets),
        )
        # Return the last error response we saw (primary or last fallback).
        if last_response is not None:
            return last_response
        # Primary was tripped and we have no fallbacks — synthesize an error.
        return LLMResponse(
            content=f"Primary model '{primary_model}' circuit open and no fallbacks available",
            finish_reason="error",
        )

    @classmethod
    def _failover_decision(cls, response: LLMResponse) -> FailoverDecision:
        status = response.error_status_code
        kind = (response.error_kind or "").lower()
        error_type = (response.error_type or "").lower()
        code = (response.error_code or "").lower()
        text = (response.content or "").lower()
        structured_values = (kind, error_type, code)
        all_values = (*structured_values, text)

        # Specific model semantics override generic wrappers such as
        # type=invalid_request_error + code=model_not_found.
        if any(token in value for value in all_values for token in _MODEL_ERROR_TOKENS):
            return FailoverDecision.NEXT_CANDIDATE
        if kind in _NON_FALLBACK_ERROR_KINDS:
            return FailoverDecision.STOP
        if any(
            token in value
            for value in structured_values
            for token in _NON_FALLBACK_ERROR_KINDS
        ):
            return FailoverDecision.STOP
        if LLMProvider.is_arrearage_response(response):
            return FailoverDecision.NEXT_PROVIDER_DOMAIN
        if kind in _PROVIDER_DOMAIN_ERROR_KINDS:
            return FailoverDecision.NEXT_PROVIDER_DOMAIN
        if any(
            token in value
            for value in all_values
            for token in _PROVIDER_DOMAIN_ERROR_TOKENS
        ):
            return FailoverDecision.NEXT_PROVIDER_DOMAIN
        if status in {401, 402, 403}:
            return FailoverDecision.NEXT_PROVIDER_DOMAIN
        if status in {400, 404, 422}:
            return FailoverDecision.STOP
        if response.error_should_retry is True:
            return FailoverDecision.NEXT_CANDIDATE
        if status is not None and (status in {408, 409, 429} or 500 <= status <= 599):
            return FailoverDecision.NEXT_CANDIDATE
        if kind in _FALLBACK_ERROR_KINDS:
            return FailoverDecision.NEXT_CANDIDATE
        if any(token in value for value in all_values for token in _FALLBACK_ERROR_TOKENS):
            return FailoverDecision.NEXT_CANDIDATE
        return FailoverDecision.STOP

    @classmethod
    def _should_fallback(cls, response: LLMResponse) -> bool:
        return cls._failover_decision(response) is not FailoverDecision.STOP
