"""Compatibility helpers while runner tests migrate to immutable runtimes."""

from __future__ import annotations

from typing import Any
from unittest.mock import DEFAULT, Mock

from nanobot.agent.runner import AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.utils.llm_runtime import LLMRuntime


def bind_default_attempt_route(provider: LLMProvider) -> None:
    """Teach spec-limited provider mocks the real single-attempt contract."""
    if not isinstance(provider, Mock):
        return

    supports_native = provider.supports_native_compaction
    if supports_native._mock_return_value is DEFAULT:
        supports_native.return_value = False
    can_resume = provider.can_resume_conversation_state
    if can_resume._mock_return_value is DEFAULT:
        can_resume.return_value = False
    build_attempt = provider._build_provider_attempt
    if build_attempt.side_effect is None and build_attempt._mock_return_value is DEFAULT:
        build_attempt.side_effect = (
            lambda **route_kwargs: LLMProvider._build_provider_attempt(
                provider,
                **route_kwargs,
            )
        )
    create_route = provider.create_attempt_route
    if create_route.side_effect is None and create_route._mock_return_value is DEFAULT:
        create_route.side_effect = (
            lambda **route_kwargs: LLMProvider.create_attempt_route(
                provider,
                **route_kwargs,
            )
        )


def make_run_spec(provider: LLMProvider, **kwargs: Any) -> AgentRunSpec:
    """Build a run spec from the pre-runtime test arguments.

    Keeping this translation in test support makes production's execution
    contract strict while avoiding irrelevant setup noise in runner behavior
    tests.  New tests should pass ``runtime`` to ``AgentRunSpec`` directly when
    runtime identity is itself under test.
    """
    bind_default_attempt_route(provider)
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
