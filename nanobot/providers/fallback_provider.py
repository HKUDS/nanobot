"""Provider wrapper that transparently fails over to fallback models on error."""

# pyright: reportIncompatibleMethodOverride=false, reportIncompatibleVariableOverride=false, reportPrivateUsage=false

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, cast

from loguru import logger

from nanobot.providers.base import (
    RETRY_AFTER_BUFFER,
    GenerationSettings,
    LLMCallObserver,
    LLMProvider,
    LLMResponse,
    ProviderAttempt,
    ProviderAttemptRoute,
    ProviderCallContext,
    ProviderConversationState,
    RetryEventCallback,
)

# Circuit breaker tuned to match OpenAICompatProvider's Responses API breaker.
_PRIMARY_FAILURE_THRESHOLD = 3
_PRIMARY_COOLDOWN_S = 60
_FALLBACK_ERROR_KINDS = frozenset({
    "timeout",
    "connection",
    "server_error",
    "rate_limit",
    "overloaded",
})
_AUTHENTICATION_ERROR_KINDS = frozenset({
    "authentication",
    "auth",
    "permission",
})
_AUTHENTICATION_ERROR_TOKENS = (
    "authentication_error",
    "authentication error",
    "invalid_api_key",
    "invalid api key",
    "incorrect_api_key",
    "incorrect api key",
    "expired_api_key",
    "expired api key",
    "invalid credential",
    "expired credential",
    "credential has expired",
    "credentials have expired",
    "invalid_token",
    "invalid token",
    "expired_token",
    "expired token",
    "unauthorized",
    "permission_denied",
    "permission denied",
    "access_denied",
    "account_deactivated",
    "organization_deactivated",
)
_NON_FALLBACK_ERROR_KINDS = frozenset({
    "content_filter",
    "refusal",
    "context_length",
    "invalid_request",
})
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


FallbackModelObserver = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _FallbackCandidate:
    provider: LLMProvider
    model: str
    generation: GenerationSettings
    context_window_tokens: int | None
    fallback_index: int | None


class _FallbackAttemptRoute:
    def __init__(
        self,
        owner: FallbackProvider,
        *,
        model: str | None,
        generation: GenerationSettings,
        context_window_tokens: int | None,
        provider_context: ProviderCallContext | None,
        on_retry_wait: RetryEventCallback | None,
        on_retry_exhausted: RetryEventCallback | None,
        on_stream_recover: Callable[[], Awaitable[None]] | None,
        fallback_stream_recovery: bool,
    ) -> None:
        self._owner = owner
        self._primary_model = model or owner._primary.get_default_model()
        self._primary_generation = generation
        self._request_context_window_tokens = context_window_tokens
        self._provider_context = provider_context
        self._on_retry_wait = on_retry_wait
        self._on_retry_exhausted = on_retry_exhausted
        self._on_stream_recover = on_stream_recover
        self._fallback_stream_recovery = fallback_stream_recovery
        self._position = -1 if owner._primary_available() else 0
        self._primary_was_attempted = self._position == -1
        self._primary_error = "unknown error"
        self._last_response: LLMResponse | None = None
        self._last_exhausted_message: str | None = None
        self._candidate: _FallbackCandidate | None = None
        self._child_route: ProviderAttemptRoute | None = None
        self._recover_before_next_attempt = False

    async def start(self) -> ProviderAttempt | LLMResponse:
        if not self._primary_was_attempted:
            logger.debug(
                "Primary model '{}' circuit open; skipping",
                self._primary_model,
            )
        return await self._start_candidate()

    async def advance(
        self,
        response: LLMResponse,
        *,
        streamed: bool,
    ) -> ProviderAttempt | LLMResponse:
        if self._child_route is None:
            return response
        step = await self._child_route.advance(response, streamed=streamed)
        if isinstance(step, ProviderAttempt):
            return step
        return await self._finish_candidate(step, streamed=streamed)

    async def _capture_exhaustion(self, message: str) -> None:
        self._last_exhausted_message = message

    def _candidate_for_position(self) -> _FallbackCandidate | None:
        if self._position == -1:
            return _FallbackCandidate(
                provider=self._owner._primary,
                model=self._primary_model,
                generation=self._primary_generation,
                context_window_tokens=(
                    self._owner._primary_context_window_tokens
                    if self._owner._primary_context_window_tokens is not None
                    else self._request_context_window_tokens
                ),
                fallback_index=None,
            )
        if self._position >= len(self._owner._fallback_presets):
            return None

        preset = self._owner._fallback_presets[self._position]
        model = preset.model
        try:
            provider = self._owner._provider_factory(preset)
            provider.set_llm_call_observer(self._owner._llm_call_observer)
        except Exception as exc:
            logger.warning(
                "Failed to create provider for fallback '{}': {}",
                model,
                exc,
            )
            return None
        return _FallbackCandidate(
            provider=provider,
            model=model,
            generation=GenerationSettings(
                max_tokens=preset.max_tokens,
                temperature=preset.temperature,
                reasoning_effort=preset.reasoning_effort,
            ),
            context_window_tokens=preset.context_window_tokens,
            fallback_index=self._position,
        )

    async def _start_candidate(self) -> ProviderAttempt | LLMResponse:
        while self._position < len(self._owner._fallback_presets):
            candidate = self._candidate_for_position()
            if candidate is None:
                self._position += 1
                continue
            self._candidate = candidate
            self._last_exhausted_message = None
            if candidate.fallback_index is not None:
                self._log_fallback_start(candidate)
            self._child_route = candidate.provider.create_attempt_route(
                model=candidate.model,
                generation=candidate.generation,
                context_window_tokens=candidate.context_window_tokens,
                provider_context=self._provider_context,
                retry_mode="standard",
                on_retry_wait=self._on_retry_wait,
                on_retry_exhausted=self._capture_exhaustion,
                on_stream_recover=self._on_stream_recover,
            )
            step = await self._child_route.start()
            if isinstance(step, ProviderAttempt):
                if self._recover_before_next_attempt:
                    self._recover_before_next_attempt = False
                    if self._on_stream_recover is not None:
                        await self._on_stream_recover()
                return step
            return await self._finish_candidate(step, streamed=False)
        return await self._finish_route()

    def _log_fallback_start(self, candidate: _FallbackCandidate) -> None:
        index = candidate.fallback_index
        if index is None:
            return
        if index == 0 and not self._primary_was_attempted:
            logger.info(
                "Primary model '{}' circuit open, trying fallback '{}'",
                self._primary_model,
                candidate.model,
            )
        elif index == 0:
            logger.info(
                "Primary model '{}' failed: {}; trying fallback '{}'",
                self._primary_model,
                self._primary_error,
                candidate.model,
            )
        else:
            logger.info(
                "Fallback '{}' also failed, trying next fallback '{}'",
                self._owner._fallback_presets[index - 1].model,
                candidate.model,
            )

    async def _finish_candidate(
        self,
        response: LLMResponse,
        *,
        streamed: bool,
    ) -> ProviderAttempt | LLMResponse:
        candidate = self._candidate
        if candidate is None:
            return response
        if response.finish_reason != "error":
            if candidate.fallback_index is None:
                self._owner._primary_failures = 0
                self._owner._primary_tripped_at = None
            else:
                await self._owner._notify_fallback_model(candidate.model)
                logger.info(
                    "Fallback '{}' succeeded after primary '{}' failed",
                    candidate.model,
                    self._primary_model,
                )
            return response

        self._last_response = response
        if streamed:
            if (response.error_kind or "").lower() != "timeout":
                logger.warning(
                    "Model error but content already streamed; skipping failover"
                )
                return response
            if (
                candidate.fallback_index is not None
                and not self._fallback_stream_recovery
            ):
                return response
            logger.warning(
                "Model '{}' stream stalled after content was emitted; "
                "starting a new stream segment and trying next fallback",
                candidate.model,
            )
            self._recover_before_next_attempt = True

        if candidate.fallback_index is None:
            self._primary_error = (response.content or self._primary_error)[:120]
            if not self._owner._should_fallback(response):
                logger.warning(
                    "Primary model '{}' returned non-fallbackable error: {}",
                    self._primary_model,
                    (response.content or "")[:120],
                )
                return response
            self._owner._primary_failures += 1
            if self._owner._primary_failures >= _PRIMARY_FAILURE_THRESHOLD:
                self._owner._primary_tripped_at = time.monotonic()
                logger.warning(
                    "Primary model '{}' circuit open after {} consecutive failures",
                    self._primary_model,
                    self._owner._primary_failures,
                )
        else:
            logger.warning(
                "Fallback '{}' also failed: {}",
                candidate.model,
                (response.content or "")[:120],
            )

        self._position = 0 if candidate.fallback_index is None else candidate.fallback_index + 1
        return await self._start_candidate()

    async def _finish_route(self) -> LLMResponse:
        logger.warning(
            "All {} fallback model(s) failed",
            len(self._owner._fallback_presets),
        )
        if self._last_response is not None:
            if self._last_exhausted_message and self._on_retry_exhausted:
                await self._on_retry_exhausted(self._last_exhausted_message)
            return replace(
                self._last_response,
                preserve_provider_state_on_error=True,
            )
        retry_after_s = (
            max(
                0.1,
                _PRIMARY_COOLDOWN_S
                - (time.monotonic() - self._owner._primary_tripped_at),
            )
            if self._owner._primary_tripped_at is not None
            else None
        )
        return LLMResponse(
            content=(
                f"Primary model '{self._primary_model}' circuit open "
                "and no fallbacks available"
            ),
            finish_reason="error",
            preserve_provider_state_on_error=True,
            error_retry_after_s=retry_after_s,
            error_should_retry=True,
        )


class _PersistentFallbackRoute:
    """Repeat the full fallback chain without mutating an emitted attempt."""

    def __init__(
        self,
        *,
        owner: FallbackProvider,
        route_factory: Callable[[], ProviderAttemptRoute],
        on_retry_wait: RetryEventCallback | None,
        on_retry_exhausted: RetryEventCallback | None,
        on_stream_recover: Callable[[], Awaitable[None]] | None,
    ) -> None:
        self._owner = owner
        self._route_factory = route_factory
        self._on_retry_wait = on_retry_wait
        self._on_retry_exhausted = on_retry_exhausted
        self._on_stream_recover = on_stream_recover
        self._route = route_factory()
        self._attempt = 0
        self._last_error_key: str | None = None
        self._identical_error_count = 0

    async def start(self) -> ProviderAttempt | LLMResponse:
        step = await self._route.start()
        if isinstance(step, ProviderAttempt):
            return step
        return await self._retry_or_finish(step, streamed=False)

    async def advance(
        self,
        response: LLMResponse,
        *,
        streamed: bool,
    ) -> ProviderAttempt | LLMResponse:
        step = await self._route.advance(response, streamed=streamed)
        if isinstance(step, ProviderAttempt):
            return step
        return await self._retry_or_finish(step, streamed=streamed)

    async def _retry_or_finish(
        self,
        response: LLMResponse,
        *,
        streamed: bool,
    ) -> ProviderAttempt | LLMResponse:
        if response.finish_reason != "error":
            return response
        if streamed:
            if (response.error_kind or "").lower() != "timeout":
                return response
            if self._on_stream_recover is not None:
                await self._on_stream_recover()

        self._attempt += 1
        error_key = ((response.content or "").strip().lower() or None)
        if error_key and error_key == self._last_error_key:
            self._identical_error_count += 1
        else:
            self._last_error_key = error_key
            self._identical_error_count = 1 if error_key else 0

        if not self._owner.is_transient_response(response):
            return response
        if self._identical_error_count >= self._owner._PERSISTENT_IDENTICAL_ERROR_LIMIT:
            logger.warning(
                "Stopping persistent retry after {} identical transient errors: {}",
                self._identical_error_count,
                (response.content or "")[:120].lower(),
            )
            if self._on_retry_exhausted is not None:
                await self._on_retry_exhausted(
                    "Persistent retry stopped after "
                    f"{self._identical_error_count} identical errors."
                )
            return response

        delays = list(self._owner._CHAT_RETRY_DELAYS)
        retry_after = self._owner._extract_retry_after_from_response(response)
        base_delay = delays[min(self._attempt - 1, len(delays) - 1)]
        delay = retry_after + RETRY_AFTER_BUFFER if retry_after else base_delay
        delay = min(delay, self._owner._PERSISTENT_MAX_DELAY)
        logger.warning(
            "LLM transient error (attempt {}{}), retrying in {}s: {}",
            self._attempt,
            "+" if self._attempt > len(delays) else f"/{len(delays)}",
            int(round(delay)),
            (response.content or "")[:120].lower(),
        )
        await self._owner._sleep_with_heartbeat(
            delay,
            attempt=self._attempt,
            persistent=True,
            on_retry_wait=self._on_retry_wait,
        )
        self._route = self._route_factory()
        next_step = await self._route.start()
        if isinstance(next_step, ProviderAttempt):
            return next_step
        return await self._retry_or_finish(next_step, streamed=False)


class FallbackProvider(LLMProvider):
    """Wrap a primary provider and transparently failover to fallback models.

    When the primary model returns a fallbackable error before content has been
    streamed, the wrapper tries each fallback model in order. Streamed timeout
    errors are the recovery exception: the caller may close the current stream
    segment, then the wrapper continues failover with later deltas in a new
    segment. Each fallback model may reside on a different provider — a factory
    callable creates the underlying provider on-the-fly.

    Key design:
    - Failover is request-scoped (the wrapper itself is stateless between turns).
    - Retrying entry points exhaust one provider's retry policy before failover.
    - Skipped when content was already streamed to avoid duplicate output,
      except timeout recovery can resume in a new stream segment.
    - Recursive failover is prevented by the factory returning plain providers.
    - Primary provider is circuit-broken after repeated failures to avoid
      wasting requests on a known-bad endpoint.
    """

    supports_stream_recover_callback = True

    def __init__(
        self,
        primary: LLMProvider,
        fallback_presets: list[Any],
        provider_factory: Callable[[Any], LLMProvider],
        fallback_model_observer: FallbackModelObserver | None = None,
        primary_context_window_tokens: int | None = None,
    ):
        primary_generation = primary.generation
        self._primary = primary
        super().__init__(provider_name=primary.provider_name)
        self._primary.generation = primary_generation
        self._fallback_presets = list(fallback_presets)
        self._provider_factory = provider_factory
        self._fallback_model_observer = fallback_model_observer
        self._primary_context_window_tokens = primary_context_window_tokens
        self._has_fallbacks = bool(fallback_presets)
        self._primary_failures = 0
        self._primary_tripped_at: float | None = None

    @property
    def generation(self) -> GenerationSettings:
        return self._primary.generation

    @generation.setter
    def generation(self, value: GenerationSettings) -> None:
        self._primary.generation = value

    def get_default_model(self) -> str:
        return self._primary.get_default_model()

    def set_fallback_model_observer(self, observer: FallbackModelObserver | None) -> None:
        """Attach a process-level observer without changing request call signatures."""
        self._fallback_model_observer = observer

    def set_llm_call_observer(self, observer: LLMCallObserver | None) -> None:
        """Attach usage recording to the primary and future fallback leaves."""
        super().set_llm_call_observer(observer)
        self._primary.set_llm_call_observer(observer)

    def can_resume_conversation_state(
        self,
        state: ProviderConversationState,
        model: str | None = None,
    ) -> bool:
        return self._primary.can_resume_conversation_state(state, model)

    def supports_native_compaction(self, model: str | None = None) -> bool:
        return self._primary.supports_native_compaction(model)

    def create_attempt_route(
        self,
        *,
        model: str | None,
        generation: GenerationSettings,
        context_window_tokens: int | None,
        provider_context: ProviderCallContext | None,
        retry_mode: str,
        on_retry_wait: RetryEventCallback | None = None,
        on_retry_exhausted: RetryEventCallback | None = None,
        on_stream_recover: Callable[[], Awaitable[None]] | None = None,
        _fallback_stream_recovery: bool | None = None,
    ) -> ProviderAttemptRoute:
        if not self._has_fallbacks:
            return self._primary.create_attempt_route(
                model=model,
                generation=generation,
                context_window_tokens=(
                    self._primary_context_window_tokens
                    if self._primary_context_window_tokens is not None
                    else context_window_tokens
                ),
                provider_context=provider_context,
                retry_mode=retry_mode,
                on_retry_wait=on_retry_wait,
                on_retry_exhausted=on_retry_exhausted,
                on_stream_recover=on_stream_recover,
            )

        def _route(
            terminal_callback: RetryEventCallback | None,
        ) -> ProviderAttemptRoute:
            return _FallbackAttemptRoute(
                self,
                model=model,
                generation=generation,
                context_window_tokens=context_window_tokens,
                provider_context=provider_context,
                on_retry_wait=on_retry_wait,
                on_retry_exhausted=terminal_callback,
                on_stream_recover=on_stream_recover,
                fallback_stream_recovery=(
                    on_stream_recover is not None
                    if _fallback_stream_recovery is None
                    else _fallback_stream_recovery
                ),
            )

        if retry_mode != "persistent":
            return _route(on_retry_exhausted)
        return _PersistentFallbackRoute(
            owner=self,
            route_factory=lambda: _route(None),
            on_retry_wait=on_retry_wait,
            on_retry_exhausted=on_retry_exhausted,
            on_stream_recover=on_stream_recover,
        )

    def _primary_available(self) -> bool:
        """Return True if the primary provider is not currently tripped."""
        if self._primary_tripped_at is None:
            return True
        if time.monotonic() - self._primary_tripped_at >= _PRIMARY_COOLDOWN_S:
            # Half-open: allow one probe attempt.
            return True
        return False

    def _generation_for_route(self, kwargs: dict[str, Any]) -> GenerationSettings:
        defaults = self.generation
        max_tokens = kwargs.get("max_tokens")
        temperature = kwargs.get("temperature")
        reasoning_effort = kwargs.get("reasoning_effort", defaults.reasoning_effort)
        return GenerationSettings(
            max_tokens=max_tokens if isinstance(max_tokens, int) else defaults.max_tokens,
            temperature=(
                temperature
                if isinstance(temperature, (int, float))
                else defaults.temperature
            ),
            reasoning_effort=(
                reasoning_effort if isinstance(reasoning_effort, str) else None
            ),
        )

    async def _execute_attempt_route(
        self,
        kwargs: dict[str, Any],
        *,
        stream: bool,
        retry: bool,
        retry_mode: str = "standard",
        on_retry_wait: RetryEventCallback | None = None,
        on_retry_exhausted: RetryEventCallback | None = None,
        on_stream_recover: Callable[[], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Execute direct and retrying entry points through one fallback policy."""
        source_kwargs = dict(kwargs)
        provider_context = source_kwargs.pop("provider_context", None)
        source_kwargs.pop("_provider_attempt", None)
        source_kwargs.pop("on_stream_recover", None)
        typed_context = (
            provider_context
            if isinstance(provider_context, ProviderCallContext)
            else None
        )
        attempt_streamed = False
        suppress_deltas = False

        async def _recover_stream() -> None:
            nonlocal attempt_streamed, suppress_deltas
            attempt_streamed = False
            if on_stream_recover is not None:
                await on_stream_recover()
            else:
                suppress_deltas = True

        route = self.create_attempt_route(
            model=source_kwargs.get("model"),
            generation=self._generation_for_route(source_kwargs),
            context_window_tokens=(
                typed_context.context_window_tokens
                if typed_context is not None
                else None
            ),
            provider_context=typed_context,
            retry_mode=retry_mode,
            on_retry_wait=on_retry_wait,
            on_retry_exhausted=on_retry_exhausted,
            on_stream_recover=_recover_stream if stream else None,
            _fallback_stream_recovery=on_stream_recover is not None,
        )
        step = await route.start()
        while isinstance(step, ProviderAttempt):
            attempt = step
            attempt_streamed = False
            original_delta = (
                None if suppress_deltas else source_kwargs.get("on_content_delta")
            )
            delta_callback = cast(
                Callable[[str], Awaitable[None]] | None,
                original_delta if callable(original_delta) else None,
            )

            async def _tracking_delta(text: str) -> None:
                nonlocal attempt_streamed
                if text:
                    attempt_streamed = True
                if delta_callback is not None:
                    await delta_callback(text)

            call_kwargs: dict[str, Any] = {
                **source_kwargs,
                "model": attempt.model,
                "max_tokens": attempt.generation.max_tokens,
                "temperature": attempt.generation.temperature,
            }
            if attempt.generation.reasoning_effort is None:
                call_kwargs.pop("reasoning_effort", None)
            else:
                call_kwargs["reasoning_effort"] = attempt.generation.reasoning_effort
            if stream:
                call_kwargs["on_content_delta"] = (
                    _tracking_delta if original_delta is not None else None
                )

            if retry:
                call_kwargs.update({
                    "retry_mode": attempt.retry_mode,
                    "on_retry_wait": attempt.on_retry_wait,
                    "on_retry_exhausted": attempt.on_retry_exhausted,
                    "provider_context": attempt.provider_context,
                    "_provider_attempt": attempt,
                })
                if stream:
                    if on_stream_recover is not None:
                        call_kwargs["on_stream_recover"] = _recover_stream
                    response = await attempt.provider.chat_stream_with_retry(**call_kwargs)
                else:
                    response = await attempt.provider.chat_with_retry(**call_kwargs)
            elif stream:
                response = await attempt.provider.chat_stream_attempt(
                    attempt=attempt,
                    provider_context=attempt.provider_context,
                    **call_kwargs,
                )
            else:
                response = await attempt.provider.chat_attempt(
                    attempt=attempt,
                    provider_context=attempt.provider_context,
                    **call_kwargs,
                )
            step = await route.advance(response, streamed=attempt_streamed)
        return step

    async def chat(self, **kwargs: Any) -> LLMResponse:
        return await self._execute_attempt_route(
            kwargs,
            stream=False,
            retry=False,
        )

    async def _run_chat_with_retry(
        self,
        kw: dict[str, Any],
        original_messages: list[dict[str, Any]],
        *,
        stream: bool,
        retry_mode: str,
        on_retry_wait: RetryEventCallback | None,
        on_retry_exhausted: RetryEventCallback | None,
        should_retry_guard: Callable[[], bool] | None = None,
        on_stream_recover: Callable[[], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        _ = original_messages, should_retry_guard
        return await self._execute_attempt_route(
            kw,
            stream=stream,
            retry=True,
            retry_mode=retry_mode,
            on_retry_wait=on_retry_wait,
            on_retry_exhausted=on_retry_exhausted,
            on_stream_recover=on_stream_recover,
        )

    async def chat_with_context(
        self,
        *,
        provider_context: ProviderCallContext,
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.chat(**kwargs, provider_context=provider_context)

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        on_stream_recover = kwargs.pop("on_stream_recover", None)
        return await self._execute_attempt_route(
            kwargs,
            stream=True,
            retry=False,
            on_stream_recover=on_stream_recover,
        )

    async def chat_stream_with_context(
        self,
        *,
        provider_context: ProviderCallContext,
        **kwargs: Any,
    ) -> LLMResponse:
        on_stream_recover = kwargs.pop("on_stream_recover", None)
        return await self.chat_stream(
            **kwargs,
            provider_context=provider_context,
            on_stream_recover=on_stream_recover,
        )

    async def _notify_fallback_model(self, model: str) -> None:
        if self._fallback_model_observer is None:
            return
        try:
            await self._fallback_model_observer(model)
        except Exception:
            logger.exception("fallback model observer failed for '{}'", model)

    @staticmethod
    def _should_fallback(response: LLMResponse) -> bool:
        if LLMProvider.is_arrearage_response(response):
            return True
        status = response.error_status_code
        kind = (response.error_kind or "").lower()
        error_type = (response.error_type or "").lower()
        code = (response.error_code or "").lower()
        text = (response.content or "").lower()
        structured_values = (kind, error_type, code)

        if kind in _AUTHENTICATION_ERROR_KINDS:
            return True
        if any(
            token in value
            for value in structured_values
            for token in _AUTHENTICATION_ERROR_TOKENS
        ):
            return True
        if kind in _NON_FALLBACK_ERROR_KINDS:
            return False
        if any(
            token in value
            for value in structured_values
            for token in _NON_FALLBACK_ERROR_KINDS
        ):
            return False
        if status in {401, 403}:
            return True
        if any(token in text for token in _AUTHENTICATION_ERROR_TOKENS):
            return True
        if response.error_should_retry is False:
            return False
        if status in {400, 404, 422}:
            return False
        if response.error_should_retry is True:
            return True
        if status is not None and (status in {408, 409, 429} or 500 <= status <= 599):
            return True
        if kind in _FALLBACK_ERROR_KINDS:
            return True
        return any(token in value for value in (kind, error_type, code, text) for token in _FALLBACK_ERROR_TOKENS)
