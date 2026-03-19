"""Sequential multi-model fallback provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse


@dataclass
class ModelCandidate:
    """A concrete model/provider pair to try in fallback order."""

    model: str
    provider_name: str
    provider: LLMProvider


class MultiModelProvider(LLMProvider):
    """Try configured model/provider candidates in order until one succeeds."""

    def __init__(self, candidates: list[ModelCandidate], default_model: str):
        super().__init__(api_key=None, api_base=None)
        if not candidates:
            raise ValueError("MultiModelProvider requires at least one candidate")
        self._candidates = candidates
        self._default_model = default_model

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
        requested_model = model or self._default_model
        ordered = self._ordered_candidates(requested_model)
        last_response: LLMResponse | None = None

        for idx, candidate in enumerate(ordered):
            if idx > 0:
                logger.warning(
                    "Primary model failed; falling back to {} via {}",
                    candidate.model,
                    candidate.provider_name,
                )

            response = await candidate.provider.chat(
                messages=messages,
                tools=tools,
                model=candidate.model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
            )
            if response.finish_reason != "error":
                return response
            last_response = response

        return last_response or LLMResponse(
            content="Error calling LLM: no fallback models configured",
            finish_reason="error",
        )

    def get_default_model(self) -> str:
        """Return the configured primary model."""
        return self._default_model

    def _ordered_candidates(self, requested_model: str) -> list[ModelCandidate]:
        if requested_model == self._default_model:
            return self._candidates

        exact = [candidate for candidate in self._candidates if candidate.model == requested_model]
        if not exact:
            return self._candidates

        remainder = [candidate for candidate in self._candidates if candidate.model != requested_model]
        return exact + remainder
