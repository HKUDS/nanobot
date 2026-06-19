"""Small helpers for passing the active LLM provider/model together."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from nanobot.providers.base import LLMProvider


@dataclass(frozen=True)
class LLMRuntime:
    provider: LLMProvider
    model: str


LLMRuntimeResolver = Callable[[], LLMRuntime]


def static_llm_runtime(provider: LLMProvider, model: str) -> LLMRuntimeResolver:
    runtime = LLMRuntime(provider=provider, model=model)
    return lambda: runtime
