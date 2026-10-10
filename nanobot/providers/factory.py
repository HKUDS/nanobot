"""Create LLM providers from config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nanobot.config.schema import (
    Config,
    InlineFallbackConfig,
    ModelPresetConfig,
    ProviderConfig,
)
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.registry import ProviderSpec, find_by_name
from nanobot.providers.routing import resolve_automatic_model_api as resolve_automatic_model_api
from nanobot.providers.routing import resolve_model_api as resolve_model_api
from nanobot.providers.routing import resolve_provider_route
from nanobot.providers.routing import validate_provider_setup as validate_provider_setup


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    signature: tuple[object, ...]
    generation: GenerationSettings | None = None
    model_preset: str | None = None


def _resolve_model_preset(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
) -> ModelPresetConfig:
    return preset if preset is not None else config.resolve_preset(preset_name)


def _provider_extra_headers(
    spec: ProviderSpec | None,
    provider_config: ProviderConfig | None,
) -> dict[str, str] | None:
    headers = dict(spec.default_extra_headers) if spec else {}
    if provider_config and provider_config.extra_headers:
        headers.update(provider_config.extra_headers)
    return headers or None


def _make_provider_core(
    config: Config,
    *,
    preset: ModelPresetConfig,
    model: str | None = None,
) -> LLMProvider:
    """Create a plain LLM provider without failover wrapping."""
    setup = resolve_provider_route(
        config,
        preset=preset,
        model=model,
    )
    model = setup.model
    provider_name = setup.provider_name
    p = setup.provider_config
    spec = setup.spec
    backend = setup.backend

    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        provider = OpenAICodexProvider(
            default_model=model,
            proxy=p.proxy,
            extra_body=p.extra_body,
            provider_name=provider_name,
        )
    elif backend == "xai_grok":
        from nanobot.providers.xai_grok_provider import XAIGrokProvider

        provider = XAIGrokProvider(
            default_model=model,
            proxy=p.proxy,
            extra_body=p.extra_body,
            provider_name=provider_name,
        )
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        if p.api_base is None:
            raise RuntimeError("validated Azure provider setup is missing api_base")
        provider = AzureOpenAIProvider(
            api_key=p.api_key or "",
            api_base=p.api_base,
            default_model=model,
            provider_name=provider_name,
        )
    elif backend == "github_copilot":
        from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

        provider = GitHubCopilotProvider(
            default_model=model, provider_name=provider_name,
            model_api=setup.model_api,
        )
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider

        custom_spec = spec if spec and spec.backend == "openai_compat" else None
        api_key = p.api_key
        if custom_spec is not None:
            api_key = api_key or "no-key"
        provider = AnthropicProvider(
            api_key=api_key,
            api_base=config.get_api_base(model, preset=preset),
            default_model=model,
            extra_headers=_provider_extra_headers(spec, p),
            extra_body=p.extra_body,
            extra_query=p.extra_query,
            proxy=p.proxy,
            spec=custom_spec,
            provider_name=provider_name,
        )
    elif backend == "bedrock":
        from nanobot.providers.bedrock_provider import BedrockProvider

        provider = BedrockProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
            region=getattr(p, "region", None),
            profile=getattr(p, "profile", None),
            extra_body=p.extra_body,
            provider_name=provider_name,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=p.api_key,
            api_base=config.get_api_base(model, preset=preset),
            default_model=model,
            extra_headers=_provider_extra_headers(spec, p),
            spec=spec,
            extra_body=p.extra_body,
            model_api=setup.model_api,
            extra_query=p.extra_query,
            proxy=p.proxy,
            provider_name=provider_name,
        )

    provider.generation = preset.to_generation_settings()
    return provider


def _inline_fallback_preset(
    primary: ModelPresetConfig,
    fallback: InlineFallbackConfig,
) -> ModelPresetConfig:
    return ModelPresetConfig(
        model=fallback.model,
        provider=fallback.provider,
        max_tokens=fallback.max_tokens if fallback.max_tokens is not None else primary.max_tokens,
        context_window_tokens=(
            fallback.context_window_tokens
            if fallback.context_window_tokens is not None
            else primary.context_window_tokens
        ),
        temperature=(
            fallback.temperature if fallback.temperature is not None else primary.temperature
        ),
        reasoning_effort=fallback.reasoning_effort,
        api=fallback.api,
    )


def _resolve_fallback_presets(config: Config, primary: ModelPresetConfig) -> list[ModelPresetConfig]:
    presets: list[ModelPresetConfig] = []
    for fallback in config.agents.defaults.fallback_models:
        if isinstance(fallback, str):
            presets.append(config.model_presets[fallback])
        else:
            presets.append(_inline_fallback_preset(primary, fallback))
    return presets


def make_provider(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
    model: str | None = None,
) -> LLMProvider:
    """Create the LLM provider implied by config.

    When *model* is given, it overrides the resolved/preset model — used by
    the failover path to create providers for fallback models.
    """
    resolved = _resolve_model_preset(config, preset_name=preset_name, preset=preset)
    provider = _make_provider_core(config, preset=resolved, model=model)
    fallback_presets = _resolve_fallback_presets(config, resolved)

    if fallback_presets:
        provider = FallbackProvider(
            primary=provider,
            fallback_presets=fallback_presets,
            provider_factory=lambda fb: _make_provider_core(config, preset=fb),
            primary_context_window_tokens=resolved.context_window_tokens,
            fallback_preset_names=[
                fallback if isinstance(fallback, str) else None
                for fallback in config.agents.defaults.fallback_models
            ],
        )

    return provider


def build_unconfigured_provider_snapshot(
    config: Config, setup_error: str, *, preset_name: str | None = None,
) -> ProviderSnapshot:
    """Keep settings available when the selected model has no usable connection."""
    from nanobot.providers.unconfigured_provider import UnconfiguredProvider

    preset = config.resolve_preset(preset_name)
    provider = UnconfiguredProvider(preset.model)
    provider.generation = preset.to_generation_settings()
    return ProviderSnapshot(
        provider=provider,
        model=preset.model,
        context_window_tokens=preset.context_window_tokens,
        signature=("unconfigured", setup_error, preset.model),
        generation=provider.generation,
        model_preset=config.agents.defaults.model_preset if preset_name is None else preset_name,
    )


def _preset_provider_signature(
    config: Config, preset: ModelPresetConfig,
) -> tuple[object, ...]:
    provider_config = config.get_provider(preset.model, preset=preset)
    provider_name = config.get_provider_name(preset.model, preset=preset)
    return (
        preset.model,
        preset.provider,
        provider_name,
        provider_config is not None,
        config.get_api_key(preset.model, preset=preset),
        config.get_api_base(preset.model, preset=preset),
        _provider_extra_headers(find_by_name(provider_name) if provider_name else None, provider_config),
        provider_config.extra_body if provider_config else None,
        provider_config.api.model_dump_json() if provider_config and provider_config.api is not None else None,
        provider_config.extra_query if provider_config else None,
        getattr(provider_config, "region", None) if provider_config else None,
        getattr(provider_config, "profile", None) if provider_config else None,
        preset.max_tokens,
        preset.temperature,
        preset.reasoning_effort,
        preset.context_window_tokens,
        preset.api.model_dump_json() if preset.api is not None else None,
        getattr(provider_config, "proxy", None) if provider_config else None,
        provider_config.thinking_style if provider_config else None,
    )


def provider_signature(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
) -> tuple[object, ...]:
    """Return the config fields that affect the active provider chain."""
    resolved = _resolve_model_preset(config, preset_name=preset_name, preset=preset)
    fallback_presets = _resolve_fallback_presets(config, resolved)
    return (
        *_preset_provider_signature(config, resolved),
        tuple(
            fallback if isinstance(fallback, str) else None
            for fallback in config.agents.defaults.fallback_models
        ),
        tuple(_preset_provider_signature(config, fallback) for fallback in fallback_presets),
    )


def build_provider_snapshot(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
) -> ProviderSnapshot:
    resolved = _resolve_model_preset(config, preset_name=preset_name, preset=preset)
    selected_preset = (
        config.agents.defaults.model_preset
        if preset_name is None and preset is None
        else preset_name
    )
    fallback_windows = [
        fallback.context_window_tokens
        for fallback in _resolve_fallback_presets(config, resolved)
    ]
    return ProviderSnapshot(
        provider=make_provider(config, preset=resolved),
        model=resolved.model,
        context_window_tokens=min([resolved.context_window_tokens, *fallback_windows]),
        signature=provider_signature(config, preset=resolved),
        generation=resolved.to_generation_settings(),
        model_preset=selected_preset,
    )


def load_provider_snapshot(
    config_path: Path | None = None,
    *,
    preset_name: str | None = None,
) -> ProviderSnapshot:
    from nanobot.config.loader import load_config, resolve_config_env_vars

    return build_provider_snapshot(
        resolve_config_env_vars(
            load_config(config_path),
            config_path=config_path,
        ),
        preset_name=preset_name,
    )
