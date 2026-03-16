"""Shared runtime helpers for provider/model resolution."""

from __future__ import annotations

from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMProvider


def resolve_subagent_model(config: Config, main_model: str | None = None) -> str:
    """Resolve the effective subagent model from config."""
    resolved_main = main_model or config.agents.defaults.model
    return config.agents.defaults.subagent_model or resolved_main


def make_provider(config: Config, model: str | None = None) -> LLMProvider:
    """Create an LLM provider for the given model using normal config resolution."""
    from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider

    resolved_model = model or config.agents.defaults.model
    provider_name = config.get_provider_name(resolved_model)
    p = config.get_provider(resolved_model)

    if provider_name == "openai_codex" or resolved_model.startswith("openai-codex/"):
        provider: LLMProvider = OpenAICodexProvider(default_model=resolved_model)
    elif provider_name == "custom":
        from nanobot.providers.custom_provider import CustomProvider

        provider = CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(resolved_model) or "http://localhost:8000/v1",
            default_model=resolved_model,
        )
    elif provider_name == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            raise RuntimeError("Azure OpenAI requires api_key and api_base.")
        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=resolved_model,
        )
    else:
        from nanobot.providers.litellm_provider import LiteLLMProvider
        from nanobot.providers.registry import find_by_name

        spec = find_by_name(provider_name)
        if not resolved_model.startswith("bedrock/") and not (p and p.api_key) and not (
            spec and (spec.is_oauth or spec.is_local)
        ):
            raise RuntimeError("No API key configured.")
        provider = LiteLLMProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(resolved_model),
            default_model=resolved_model,
            extra_headers=p.extra_headers if p else None,
            provider_name=provider_name,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider
