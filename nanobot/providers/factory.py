"""Provider construction helpers shared by CLI and runtime."""

from __future__ import annotations

from typing import Any

from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.providers.fallback_provider import FallbackCandidate, FallbackProvider
from nanobot.providers.registry import find_by_name


def _resolve_provider(config: Any, model: str, provider_override: str | None = None):
    forced = provider_override or "auto"
    if forced != "auto":
        spec = find_by_name(forced)
        if spec is None:
            raise ValueError(f"Unknown provider '{forced}'.")
        provider_config = getattr(config.providers, spec.name, None)
        return provider_config, spec.name, spec

    provider_name = config.get_provider_name(model)
    provider_config = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    return provider_config, provider_name, spec


def _resolve_api_base(provider_config: Any, spec: Any) -> str | None:
    """Resolve API base URL from already-matched provider config and spec.

    This mirrors the logic in ``Config.get_api_base()`` but operates on
    pre-resolved objects.  We cannot call ``get_api_base(model)`` directly
    because it re-resolves the provider via ``_match_provider(model)`` which
    only reads ``agents.defaults.provider`` — that would return the wrong
    provider config for fallback targets that override the provider.
    """
    if provider_config and provider_config.api_base:
        return provider_config.api_base
    if spec and spec.default_api_base:
        return spec.default_api_base
    return None


def build_single_provider(config: Any, model: str, provider_override: str | None = None) -> tuple[LLMProvider, str]:
    provider_config, provider_name, spec = _resolve_provider(config, model, provider_override)
    backend = spec.backend if spec else "openai_compat"

    if backend == "azure_openai":
        if not provider_config or not provider_config.api_key or not provider_config.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base in config.")
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (provider_config and provider_config.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{provider_name}'.")

    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        provider = OpenAICodexProvider(default_model=model)
    elif backend == "github_copilot":
        from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

        provider = GitHubCopilotProvider(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=provider_config.api_key,
            api_base=provider_config.api_base,
            default_model=model,
        )
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=_resolve_api_base(provider_config, spec),
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=_resolve_api_base(provider_config, spec),
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            spec=spec,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider, provider_name or "unknown"


def build_provider(config: Any) -> LLMProvider:
    defaults = config.agents.defaults
    primary_provider, primary_name = build_single_provider(
        config,
        defaults.model,
        defaults.provider,
    )
    if not defaults.fallbacks:
        return primary_provider

    candidates = [
        FallbackCandidate(
            provider=primary_provider,
            model=defaults.model,
            provider_name=primary_name,
        )
    ]
    for target in defaults.fallbacks:
        provider, provider_name = build_single_provider(config, target.model, target.provider)
        candidates.append(
            FallbackCandidate(
                provider=provider,
                model=target.model,
                provider_name=provider_name,
            )
        )
    return FallbackProvider(candidates)
