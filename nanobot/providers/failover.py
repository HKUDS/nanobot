"""Provider-like failover router used after provider-local retry is exhausted."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


class ModelRouter(LLMProvider):
    """Try fallback model candidates for eligible transient final errors."""

    def __init__(
        self,
        *,
        primary_provider: LLMProvider,
        primary_model: str,
        fallback_presets: list[str],
        provider_factory: Callable[[str], LLMProvider] | None = None,
        per_candidate_timeout_s: float | None = None,
    ) -> None:
        super().__init__(
            api_key=getattr(primary_provider, "api_key", None),
            api_base=getattr(primary_provider, "api_base", None),
        )
        self.primary_provider = primary_provider
        self.primary_model = primary_model
        self.fallback_presets = list(fallback_presets)
        self._provider_factory = provider_factory
        self._provider_cache: dict[str, LLMProvider] = {}
        self.per_candidate_timeout_s = per_candidate_timeout_s
        self.generation = getattr(primary_provider, "generation", GenerationSettings())

    def get_default_model(self) -> str:
        return self.primary_model

    async def chat(self, **kwargs: Any) -> LLMResponse:
        async def call(provider: LLMProvider, candidate_model: str, _unused_delta: Any) -> LLMResponse:
            return await provider.chat(**{**kwargs, "model": candidate_model})
        return await self._route(call)

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        async def call(provider: LLMProvider, candidate_model: str, content_delta: Any) -> LLMResponse:
            return await provider.chat_stream(
                **{**kwargs, "model": candidate_model, "on_content_delta": content_delta}
            )
        return await self._route(call, on_content_delta=kwargs.get("on_content_delta"))

    @property
    def supports_progress_deltas(self) -> bool:  # type: ignore[override]
        return getattr(self.primary_provider, "supports_progress_deltas", False)

    @classmethod
    def _should_failover(cls, response: LLMResponse) -> bool:
        if response.finish_reason != "error":
            return False
        if response.error_should_retry is False:
            return False
        if response.error_kind == "configuration":
            return False
        return True

    def _resolve(self, model: str) -> tuple[LLMProvider, str]:
        """Return (provider, actual_model_name) for a preset name.

        Caches results so factory is only invoked once per unique name.
        """
        if model in self._provider_cache:
            cached_provider = self._provider_cache[model]
            return cached_provider, cached_provider.get_default_model()
        if self._provider_factory is None:
            raise ValueError(
                f"Cannot resolve fallback model {model!r}: no provider_factory configured"
            )
        provider = self._provider_factory(model)
        self._provider_cache[model] = provider
        return provider, provider.get_default_model()

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
    def _resolver_error(label: str, exc: Exception) -> LLMResponse:
        logger.warning("Failed to resolve fallback model {}: {}", label, exc)
        return LLMResponse(
            content=f"Error configuring fallback model {label}: {exc}",
            finish_reason="error",
            error_kind="configuration",
            error_should_retry=False,
        )

    async def _route(
        self,
        call: Callable[[LLMProvider, str, Callable[[str], Awaitable[None]] | None], Awaitable[LLMResponse]],
        *,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Try primary then each fallback candidate, lazily resolving providers."""

        async def _try_one(label: str, provider: LLMProvider, model: str) -> LLMResponse:
            try:
                return await self._with_timeout(call(provider, model, on_content_delta))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return self._resolver_error(label, exc)

        # Primary
        response = await _try_one("primary", self.primary_provider, self.primary_model)
        if response.finish_reason != "error":
            return response
        if not self._should_failover(response):
            return response

        # Fallbacks
        for name in self.fallback_presets:
            try:
                provider, model = self._resolve(name)
            except Exception as exc:
                logger.warning("Failed to resolve fallback model {}: {}", name, exc)
                return self._resolver_error(name, exc)

            response = await _try_one(name, provider, model)
            if response.finish_reason != "error":
                logger.info("LLM failover selected model={}", name)
                return response
            if not self._should_failover(response):
                return response

        logger.warning("LLM failover exhausted after all candidates")
        return response

    async def chat_with_retry(self, **kwargs: Any) -> LLMResponse:
        async def call(
            provider: LLMProvider, candidate_model: str, _unused_delta: Any
        ) -> LLMResponse:
            return await provider.chat_with_retry(
                **{**kwargs, "model": candidate_model}
            )
        return await self._route(call)

    async def chat_stream_with_retry(self, **kwargs: Any) -> LLMResponse:
        on_content_delta = kwargs.pop("on_content_delta", None)

        async def call(
            provider: LLMProvider,
            candidate_model: str,
            content_delta: Callable[[str], Awaitable[None]] | None,
        ) -> LLMResponse:
            buffered: list[str] = []

            async def buffer_delta(delta: str) -> None:
                buffered.append(delta)

            kwargs["on_content_delta"] = buffer_delta if content_delta else None
            response = await provider.chat_stream_with_retry(
                **{**kwargs, "model": candidate_model}
            )
            if response.finish_reason != "error" and content_delta:
                try:
                    for delta in buffered:
                        await content_delta(delta)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Failover delta callback failed for model={}", candidate_model)
            return response

        return await self._route(call, on_content_delta=on_content_delta)
