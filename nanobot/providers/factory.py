"""Create LLM providers from config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.providers.failover import ModelCandidate, ModelRouter
from nanobot.providers.registry import find_by_name


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    signature: tuple[object, ...]
    fallback_models: tuple[str, ...] = ()


def make_provider(config: Config) -> LLMProvider:
    """Create the LLM provider implied by config."""
    return make_provider_for_model(config, config.agents.defaults.model)


def make_provider_for_model(config: Config, model: str) -> LLMProvider:
    """Create the LLM provider candidate for a specific model string."""
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    if backend == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base in config.")
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (p and p.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{provider_name}'.")

    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        provider = OpenAICodexProvider(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )
    elif backend == "github_copilot":
        from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

        provider = GitHubCopilotProvider(default_model=model)
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider


def _provider_config_signature(config: Config, model: str) -> tuple[object, ...]:
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)
    extra_headers: tuple[tuple[str, str], ...] = ()
    if p and p.extra_headers:
        extra_headers = tuple(sorted((str(k), str(v)) for k, v in p.extra_headers.items()))
    return (
        model,
        provider_name,
        config.get_api_key(model),
        config.get_api_base(model),
        extra_headers,
    )


def _failover_signature(config: Config) -> tuple[Any, ...]:
    defaults = config.agents.defaults
    failover = defaults.failover
    return (
        tuple(defaults.fallback_models),
        failover.enabled,
        failover.cooldown_seconds,
        failover.max_switches_per_turn,
        failover.failover_on_quota,
    )


def provider_signature(config: Config) -> tuple[object, ...]:
    """Return the config fields that affect the primary LLM provider."""
    model = config.agents.defaults.model
    defaults = config.agents.defaults
    candidate_models = (model, *defaults.fallback_models)
    return (
        defaults.provider,
        tuple(_provider_config_signature(config, candidate) for candidate in candidate_models),
        defaults.max_tokens,
        defaults.temperature,
        defaults.reasoning_effort,
        defaults.context_window_tokens,
        _failover_signature(config),
    )


def _make_fallback_candidates(config: Config) -> list[ModelCandidate]:
    candidates: list[ModelCandidate] = []
    for model in config.agents.defaults.fallback_models:
        provider_name = config.get_provider_name(model)
        candidates.append(
            ModelCandidate(
                model=model,
                provider_name=provider_name,
                provider_factory=lambda m=model: make_provider_for_model(config, m),
            )
        )
    return candidates


def build_provider_snapshot(config: Config) -> ProviderSnapshot:
    defaults = config.agents.defaults
    primary = make_provider(config)
    provider: LLMProvider = primary
    fallback_models = tuple(defaults.fallback_models)
    if defaults.failover.enabled and fallback_models:
        provider = ModelRouter(
            primary_provider=primary,
            primary_model=defaults.model,
            primary_provider_name=config.get_provider_name(defaults.model),
            fallback_candidates=_make_fallback_candidates(config),
            failover=defaults.failover,
        )
    return ProviderSnapshot(
        provider=provider,
        model=defaults.model,
        context_window_tokens=defaults.context_window_tokens,
        signature=provider_signature(config),
        fallback_models=fallback_models,
    )


def load_provider_snapshot(config_path: Path | None = None) -> ProviderSnapshot:
    from nanobot.config.loader import load_config, resolve_config_env_vars

    return build_provider_snapshot(resolve_config_env_vars(load_config(config_path)))
