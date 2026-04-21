"""Runtime provider wrapper that adds explicit ordered fallback candidates."""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse


@dataclass(frozen=True)
class FallbackCandidate:
    """One runtime provider/model candidate in the fallback chain."""

    provider: LLMProvider
    model: str
    provider_name: str

    @property
    def label(self) -> str:
        return f"{self.provider_name}/{self.model}"


class FallbackProvider(LLMProvider):
    """Wrap ordered providers and fail over on transient terminal errors."""

    def __init__(self, candidates: list[FallbackCandidate]):
        if not candidates:
            raise ValueError("FallbackProvider requires at least one candidate")
        super().__init__()
        self._candidates = list(candidates)
        self.generation = candidates[0].provider.generation

    def get_default_model(self) -> str:
        return self._candidates[0].model

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
        candidate = self._candidates[0]
        return await candidate.provider.chat(
            messages=messages,
            tools=tools,
            model=model or candidate.model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
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
    ) -> LLMResponse:
        candidate = self._candidates[0]
        return await candidate.provider.chat_stream(
            messages=messages,
            tools=tools,
            model=model or candidate.model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            on_content_delta=on_content_delta,
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
        return await self._call_with_fallback(
            stream=False,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            retry_mode=retry_mode,
            on_retry_wait=on_retry_wait,
        )

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
        return await self._call_with_fallback(
            stream=True,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            on_content_delta=on_content_delta,
            retry_mode=retry_mode,
            on_retry_wait=on_retry_wait,
        )

    async def _call_with_fallback(
        self,
        *,
        stream: bool,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: object,
        temperature: object,
        reasoning_effort: object,
        tool_choice: str | dict[str, Any] | None,
        retry_mode: str,
        on_retry_wait: Callable[[str], Awaitable[None]] | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        last_response: LLMResponse | None = None
        active_candidates = [
            FallbackCandidate(candidate.provider, model or candidate.model, candidate.provider_name)
            for candidate in self._candidates
        ]

        for index, candidate in enumerate(active_candidates, start=1):
            emitted_delta = False

            async def _wrapped_delta(delta: str) -> None:
                nonlocal emitted_delta
                if delta:
                    emitted_delta = True
                    if on_content_delta:
                        await on_content_delta(delta)

            resolved_max_tokens = (
                candidate.provider.generation.max_tokens
                if max_tokens is self._SENTINEL or max_tokens is None
                else max_tokens
            )
            resolved_temperature = (
                candidate.provider.generation.temperature
                if temperature is self._SENTINEL or temperature is None
                else temperature
            )
            resolved_reasoning_effort = (
                candidate.provider.generation.reasoning_effort
                if reasoning_effort is self._SENTINEL
                else reasoning_effort
            )

            request_kwargs: dict[str, Any] = {
                "messages": copy.deepcopy(messages),
                "tools": tools,
                "model": candidate.model,
                "max_tokens": resolved_max_tokens,
                "temperature": resolved_temperature,
                "reasoning_effort": resolved_reasoning_effort,
                "tool_choice": tool_choice,
            }
            if stream:
                request_kwargs["on_content_delta"] = _wrapped_delta

                async def _call_stream_once(**inner_kwargs: Any) -> LLMResponse:
                    response = await candidate.provider._safe_chat_stream(**inner_kwargs)
                    if emitted_delta and response.finish_reason == "error":
                        response = replace(response, error_should_retry=False)
                    return response

                response = await candidate.provider._run_with_retry(
                    _call_stream_once,
                    request_kwargs,
                    request_kwargs["messages"],
                    retry_mode=retry_mode,
                    on_retry_wait=on_retry_wait,
                )
            else:
                response = await candidate.provider.chat_with_retry(
                    **request_kwargs,
                    retry_mode=retry_mode,
                    on_retry_wait=on_retry_wait,
                )

            if response.finish_reason != "error":
                return response

            last_response = response
            if stream and emitted_delta:
                logger.warning(
                    "LLM fallback disabled after partial streamed output from {}",
                    candidate.label,
                )
                return response

            if not candidate.provider._is_transient_response(response):
                return response

            if index >= len(active_candidates):
                return response

            next_candidate = active_candidates[index]
            logger.warning(
                "LLM fallback: {} -> {} after transient error: {}",
                candidate.label,
                next_candidate.label,
                (response.content or "")[:160].lower(),
            )

        return last_response if last_response is not None else LLMResponse(
            content="LLM fallback exhausted",
            finish_reason="error",
        )
