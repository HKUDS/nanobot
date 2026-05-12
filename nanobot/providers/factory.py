"""Create LLM providers from config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.base import LLMProvider
from nanobot.providers.registry import find_by_name


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    signature: tuple[object, ...]


def _resolve_model_preset(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
) -> ModelPresetConfig:
    return preset if preset is not None else config.resolve_preset(preset_name)


def make_provider(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
) -> LLMProvider:
    """Create the LLM provider implied by config."""
    resolved = _resolve_model_preset(config, preset_name=preset_name, preset=preset)
    model = resolved.model
    provider_name = config.get_provider_name(model, preset=resolved)
    p = config.get_provider(model, preset=resolved)
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
            api_base=config.get_api_base(model, preset=resolved),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    elif backend == "bedrock":
        from nanobot.providers.bedrock_provider import BedrockProvider

        provider = BedrockProvider(
            api_key=p.api_key if p else None,
            api_base=p.api_base if p else None,
            default_model=model,
            region=getattr(p, "region", None) if p else None,
            profile=getattr(p, "profile", None) if p else None,
            extra_body=p.extra_body if p else None,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model, preset=resolved),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
            extra_body=p.extra_body if p else None,
        )

    provider.generation = resolved.to_generation_settings()
    return provider


def provider_signature(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
) -> tuple[object, ...]:
    """Return the config fields that affect the primary LLM provider."""
    resolved = _resolve_model_preset(config, preset_name=preset_name, preset=preset)
    p = config.get_provider(resolved.model, preset=resolved)
    return (
        resolved.model,
        resolved.provider,
        config.get_provider_name(resolved.model, preset=resolved),
        config.get_api_key(resolved.model, preset=resolved),
        config.get_api_base(resolved.model, preset=resolved),
        p.extra_headers if p else None,
        p.extra_body if p else None,
        getattr(p, "region", None) if p else None,
        getattr(p, "profile", None) if p else None,
        resolved.max_tokens,
        resolved.temperature,
        resolved.reasoning_effort,
        resolved.context_window_tokens,
    )


def build_provider_snapshot(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
) -> ProviderSnapshot:
    resolved = _resolve_model_preset(config, preset_name=preset_name, preset=preset)
    return ProviderSnapshot(
        provider=make_provider(config, preset=resolved),
        model=resolved.model,
        context_window_tokens=resolved.context_window_tokens,
        signature=provider_signature(config, preset=resolved),
    )


def load_provider_snapshot(config_path: Path | None = None) -> ProviderSnapshot:
    from nanobot.config.loader import load_config, resolve_config_env_vars

    return build_provider_snapshot(resolve_config_env_vars(load_config(config_path)))
