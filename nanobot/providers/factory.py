"""Shared LLM provider construction and validation."""

from __future__ import annotations

from nanobot.config.schema import Config

MINIMAX_ANTHROPIC_BASE_KEYWORD = "api.minimaxi.com/anthropic"


class ProviderConfigurationError(ValueError):
    """Raised when the configured provider cannot be constructed safely."""


def _resolve_minimax_compatible_provider(
    config: Config,
    provider_name: str | None,
    provider_config,
    model: str,
) -> tuple[str | None, object | None, str, str | None]:
    if provider_name != "minimax":
        return provider_name, provider_config, model, None
    if provider_config and provider_config.api_key:
        return provider_name, provider_config, model, None
    if "minimax" not in model.lower():
        return provider_name, provider_config, model, None

    anthropic_config = getattr(config.providers, "anthropic", None)
    if not anthropic_config or not anthropic_config.api_key or not anthropic_config.api_base:
        return provider_name, provider_config, model, None
    if MINIMAX_ANTHROPIC_BASE_KEYWORD not in anthropic_config.api_base:
        return provider_name, provider_config, model, None

    compat_model = model.split("/", 1)[1] if "/" in model else model
    return "anthropic", anthropic_config, f"anthropic/{compat_model}", anthropic_config.api_base


def create_provider(config: Config):
    """Create the active LLM provider from config or raise ProviderConfigurationError."""
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
    from nanobot.providers.custom_provider import CustomProvider
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
    from nanobot.providers.registry import find_by_name

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    provider_config = config.get_provider(model)
    provider_name, provider_config, model, api_base_override = _resolve_minimax_compatible_provider(
        config,
        provider_name,
        provider_config,
        model,
    )
    resolved_api_base = api_base_override or config.get_api_base(model)

    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        provider = OpenAICodexProvider(default_model=model)
    elif provider_name == "custom":
        if not provider_config or not provider_config.api_base:
            raise ProviderConfigurationError("`providers.custom.apiBase` is missing.")
        if not provider_config.api_key:
            raise ProviderConfigurationError("`providers.custom.apiKey` is missing.")
        provider = CustomProvider(
            api_key=provider_config.api_key,
            api_base=resolved_api_base or provider_config.api_base,
            default_model=model,
        )
    elif provider_name == "azure_openai":
        if not provider_config or not provider_config.api_key:
            raise ProviderConfigurationError("`providers.azure_openai.apiKey` is missing.")
        if not provider_config.api_base:
            raise ProviderConfigurationError("`providers.azure_openai.apiBase` is missing.")
        provider = AzureOpenAIProvider(
            api_key=provider_config.api_key,
            api_base=provider_config.api_base,
            default_model=model,
        )
    else:
        spec = find_by_name(provider_name) if provider_name else None
        if not spec:
            raise ProviderConfigurationError(
                f"Unknown provider `{provider_name or 'auto'}` for model `{model}`."
            )
        if not model.startswith("bedrock/") and not spec.is_local and not spec.is_oauth:
            if not provider_config or not provider_config.api_key:
                raise ProviderConfigurationError(
                    f"`providers.{spec.name}.apiKey` is missing."
                )
        provider = LiteLLMProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=resolved_api_base,
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            provider_name=provider_name,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider
