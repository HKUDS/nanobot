"""Create LLM providers from config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.providers.registry import find_by_name

if TYPE_CHECKING:
    from nanobot.config.schema import ModelPresetConfig, ProviderConfig
    from nanobot.providers.registry import ProviderSpec


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    signature: tuple[object, ...]


@dataclass(frozen=True)
class _ProviderInfo:
    """Resolved metadata needed to build and validate an LLM provider."""

    name: str | None
    cfg: ProviderConfig | None
    spec: ProviderSpec | None
    api_base: str | None
    backend: str


def _resolve_provider_info(
    config: Config,
    model: str,
    preset: ModelPresetConfig,
) -> _ProviderInfo:
    """Derive provider name, config, spec and api_base from preset or auto-detection."""
    if preset.provider != "auto":
        name = preset.provider
        cfg = getattr(config.providers, name, None)
        spec = find_by_name(name)
        api_base = (
            cfg.api_base
            if cfg and cfg.api_base
            else (spec.default_api_base if spec and spec.default_api_base else None)
        )
    else:
        name = config.get_provider_name(model)
        cfg = config.get_provider(model)
        spec = find_by_name(name) if name else None
        api_base = config.get_api_base(model)

    backend = spec.backend if spec else "openai_compat"
    return _ProviderInfo(name=name, cfg=cfg, spec=spec, api_base=api_base, backend=backend)


def _validate_provider(info: _ProviderInfo, model: str) -> None:
    """Ensure credentials / endpoints are present before instantiation."""
    cfg = info.cfg
    backend = info.backend
    name = info.name

    if backend == "azure_openai":
        if not cfg or not cfg.api_key or not cfg.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base in config.")
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (cfg and cfg.api_key)
        exempt = info.spec and (info.spec.is_oauth or info.spec.is_local or info.spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{name}'.")


def _create_provider(model: str, info: _ProviderInfo) -> LLMProvider:
    """Instantiate the concrete provider class for *backend*."""
    cfg = info.cfg
    backend = info.backend

    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        provider = OpenAICodexProvider(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=cfg.api_key if cfg else None,
            api_base=info.api_base,
            default_model=model,
        )
    elif backend == "github_copilot":
        from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

        provider = GitHubCopilotProvider(default_model=model)
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=cfg.api_key if cfg else None,
            api_base=info.api_base,
            default_model=model,
            extra_headers=cfg.extra_headers if cfg else None,
        )
    elif backend == "bedrock":
        from nanobot.providers.bedrock_provider import BedrockProvider

        provider = BedrockProvider(
            api_key=cfg.api_key if cfg else None,
            api_base=info.api_base if cfg else None,
            default_model=model,
            region=getattr(cfg, "region", None) if cfg else None,
            profile=getattr(cfg, "profile", None) if cfg else None,
            extra_body=cfg.extra_body if cfg else None,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=cfg.api_key if cfg else None,
            api_base=info.api_base,
            default_model=model,
            extra_headers=cfg.extra_headers if cfg else None,
            spec=info.spec,
            extra_body=cfg.extra_body if cfg else None,
        )
    return provider


def _apply_generation(provider: LLMProvider, preset: ModelPresetConfig) -> None:
    provider.generation = GenerationSettings(
        temperature=preset.temperature,
        max_tokens=preset.max_tokens,
        reasoning_effort=preset.reasoning_effort,
    )


def build_provider_for_preset(config: Config, preset: ModelPresetConfig) -> LLMProvider:
    """Create an LLM provider from a full *preset* (model + provider + generation)."""
    info = _resolve_provider_info(config, preset.model, preset)
    _validate_provider(info, preset.model)
    provider = _create_provider(preset.model, info)
    _apply_generation(provider, preset)
    return provider


def make_provider(config: Config) -> LLMProvider:
    """Create the LLM provider implied by config (legacy entrypoint)."""
    resolved = config.resolve_preset()
    return build_provider_for_preset(config, resolved)


def make_provider_factory(config: Config):
    """Build a cached factory that creates providers for preset names.

    The factory looks up *preset_name* in ``config.model_presets`` and builds
    the provider from the preset's full configuration.
    """
    cache: dict[str, LLMProvider] = {}
    presets = config.model_presets

    def factory(preset_name: str) -> LLMProvider:
        preset = presets.get(preset_name)
        if preset is None:
            raise ValueError(f"Preset {preset_name!r} not found in model_presets")
        if preset_name not in cache:
            cache[preset_name] = build_provider_for_preset(config, preset)
        return cache[preset_name]

    return factory


def provider_signature(config: Config) -> tuple[object, ...]:
    """Return the config fields that affect the primary LLM provider."""
    resolved = config.resolve_preset()
    defaults = config.agents.defaults
    return (
        resolved.model,
        resolved.provider,
        config.get_provider_name(resolved.model),
        config.get_api_key(resolved.model),
        config.get_api_base(resolved.model),
        resolved.max_tokens,
        resolved.temperature,
        resolved.reasoning_effort,
        resolved.context_window_tokens,
        tuple(defaults.fallback_presets),
    )


def build_provider_snapshot(config: Config) -> ProviderSnapshot:
    resolved = config.resolve_preset()
    return ProviderSnapshot(
        provider=make_provider(config),
        model=resolved.model,
        context_window_tokens=resolved.context_window_tokens,
        signature=provider_signature(config),
    )


def load_provider_snapshot(config_path: Path | None = None) -> ProviderSnapshot:
    from nanobot.config.loader import load_config, resolve_config_env_vars

    return build_provider_snapshot(resolve_config_env_vars(load_config(config_path)))
