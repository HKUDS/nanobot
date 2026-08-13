"""Compatibility helpers while runner tests migrate to immutable runtimes."""

from __future__ import annotations

from typing import Any

from nanobot.agent.runner import AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.utils.llm_runtime import LLMRuntime


def make_run_spec(provider: LLMProvider, **kwargs: Any) -> AgentRunSpec:
    """Build a run spec from the pre-runtime test arguments.

    Keeping this translation in test support makes production's execution
    contract strict while avoiding irrelevant setup noise in runner behavior
    tests.  New tests should pass ``runtime`` to ``AgentRunSpec`` directly when
    runtime identity is itself under test.
    """
    model = kwargs.pop("model")
    context_window_tokens = kwargs.pop(
        "context_window_tokens",
        AgentDefaults().context_window_tokens,
    )
    provider_generation = getattr(provider, "generation", None)
    defaults = GenerationSettings()

    temperature = kwargs.pop("temperature", None)
    if temperature is None:
        candidate = getattr(provider_generation, "temperature", None)
        temperature = candidate if isinstance(candidate, (int, float)) else defaults.temperature

    max_tokens = kwargs.pop("max_tokens", None)
    if max_tokens is None:
        candidate = getattr(provider_generation, "max_tokens", None)
        max_tokens = candidate if isinstance(candidate, int) else defaults.max_tokens

    reasoning_effort = kwargs.pop("reasoning_effort", None)
    if reasoning_effort is None:
        candidate = getattr(provider_generation, "reasoning_effort", None)
        reasoning_effort = candidate if isinstance(candidate, str) else None

    runtime = LLMRuntime(
        provider=provider,
        model=model,
        generation=GenerationSettings(
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        ),
        context_window_tokens=context_window_tokens,
    )
    return AgentRunSpec(runtime=runtime, **kwargs)
