"""Create LLM providers from config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nanobot.config.schema import (
    Config,
    InlineFallbackConfig,
    ModelAPIConfig,
    ModelPresetConfig,
    ProviderConfig,
)
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.registry import (
    ModelAPICapabilities,
    ProviderAPI,
    ProviderSpec,
    RequestAPI,
    create_dynamic_spec,
    find_by_name,
)


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    signature: tuple[object, ...]
    generation: GenerationSettings | None = None
    model_preset: str | None = None


@dataclass(frozen=True)
class _ProviderSetup:
    model: str
    provider_name: str
    provider_config: ProviderConfig | None
    spec: ProviderSpec | None
    backend: str
    model_api: ModelAPICapabilities | None


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


def _provider_spec_for_config(
    provider_name: str,
    provider_config: ProviderConfig | None,
) -> ProviderSpec | None:
    spec = find_by_name(provider_name)
    if (
        spec is not None
        and spec.name == "orcarouter"
        and provider_config is not None
        and provider_config.api_base
        and provider_config.api_base.rstrip("/").lower()
        != spec.default_api_base.rstrip("/").lower()
    ):
        # Before OrcaRouter became a built-in provider, this name was valid for a
        # dynamic custom provider. Preserve that provider's model-prefix behavior
        # when an existing config points the name at a different endpoint.
        return create_dynamic_spec(
            provider_name,
            display_name=provider_config.display_name or "",
            thinking_style=provider_config.thinking_style or "",
        )
    return spec


def resolve_model_api(
    spec: ProviderSpec,
    provider_config: ProviderConfig | None,
    preset_api: ModelAPIConfig | None,
) -> ModelAPICapabilities | None:
    """Apply the connection's API ceiling and default to a model declaration."""
    connection_api = provider_config.api if provider_config else None
    if connection_api is not None:
        if not spec.provider_api_configurable:
            raise ValueError(f"Provider '{spec.name}' does not support connection API declarations.")
        spec.validate_model_api(connection_api.to_capabilities())
    if preset_api is not None:
        api = preset_api.to_capabilities()
        spec.validate_model_api(api)
        if connection_api is not None:
            unsupported = set(api.supported_apis) - set(connection_api.supported_apis)
            if unsupported:
                raise ValueError(
                    f"Provider '{spec.name}' does not accept request APIs: {', '.join(sorted(unsupported))}"
                )
        return api
    if connection_api is None:
        return None
    api = connection_api.to_capabilities()
    # Selecting a default adapter does not authorize fallback across API families.
    supported: tuple[RequestAPI, ...] = ("anthropic_messages",) if api.preferred_api == "anthropic_messages" else tuple(
        item for item in api.supported_apis if item != "anthropic_messages"
    )
    return ModelAPICapabilities(supported_apis=supported, preferred_api=api.preferred_api)


def _resolve_provider_setup(
    config: Config,
    *,
    preset: ModelPresetConfig,
    model: str | None = None,
) -> _ProviderSetup:
    """Resolve and validate provider configuration without constructing a client."""
    model = model or preset.model
    provider_name = config.get_provider_name(model, preset=preset)
    p = config.get_provider(model, preset=preset)
    if not provider_name:
        raise ValueError(f"No provider is configured for model '{model}'.")
    spec = _provider_spec_for_config(provider_name, p)
    if not spec and p:
        if not p.api_base:
            raise ValueError(f"Provider '{provider_name}' requires api_base in config.")
        spec = create_dynamic_spec(
            provider_name,
            display_name=(p.display_name or "") if p else "",
            thinking_style=(p.thinking_style or "") if p else "",
        )
    if spec and spec.is_transcription_only:
        raise ValueError(f"Provider '{provider_name}' only supports transcription.")
    backend = spec.backend if spec else "openai_compat"
    model_api = resolve_model_api(spec, p, preset.api) if spec is not None else None
    if model_api is not None and model_api.preferred_api == "anthropic_messages":
        backend = "anthropic"
    if p and p.proxy and backend not in {"openai_compat", "openai_codex", "xai_grok", "anthropic"}:
        raise ValueError(
            f"providers.{provider_name}.proxy is only supported for "
            "OpenAI-compatible providers, Anthropic Messages, OpenAI Codex, and xAI Grok."
        )

    if backend == "azure_openai":
        if not p or not p.api_base:
            raise ValueError("Azure OpenAI requires api_base in config.")
    elif (
        backend in {"openai_compat", "anthropic"}
        and spec
        and spec.is_direct
        and not spec.default_api_base
        and not (p and p.api_base)
    ):
        raise ValueError(f"Provider '{provider_name}' requires api_base in config.")
    elif backend in {"anthropic", "openai_compat"} and not (
        backend == "openai_compat" and model.startswith("bedrock/")
    ):
        needs_key = not (p and p.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{provider_name}'.")

    return _ProviderSetup(
        model=model,
        provider_name=provider_name,
        provider_config=p,
        spec=spec,
        backend=backend,
        model_api=model_api,
    )


def resolve_automatic_model_api(
    config: Config, *, preset: ModelPresetConfig,
) -> tuple[str, ProviderAPI]:
    """Preview the default request API without live requests or circuit-breaker state."""
    setup = _resolve_provider_setup(config, preset=preset.model_copy(update={"api": None}))
    if setup.model_api is not None:
        return setup.provider_name, setup.model_api.preferred_api
    spec = setup.spec
    if spec is None:
        return setup.provider_name, "chat_completions"
    if len(spec.request_apis) == 1:
        return setup.provider_name, spec.request_apis[0]
    provider_config = setup.provider_config
    if setup.backend == "github_copilot":
        from nanobot.providers.github_copilot_provider import cached_github_copilot_model_api

        api = cached_github_copilot_model_api(
            setup.model, provider_config.proxy if provider_config else None,
        )
        if api is not None:
            return setup.provider_name, api.preferred_api
    api = spec.default_model_api(
        setup.model, preset.reasoning_effort,
        api_base=config.get_api_base(setup.model, preset=preset),
        api_type=provider_config.api_type if provider_config else "auto",
        extra_body=provider_config.extra_body if provider_config else None,
    )
    return setup.provider_name, api.preferred_api


def validate_provider_setup(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
    model: str | None = None,
) -> None:
    """Validate local provider/model settings without loading a provider client."""
    resolved = _resolve_model_preset(config, preset_name=preset_name, preset=preset)
    _resolve_provider_setup(
        config,
        preset=resolved,
        model=model,
    )


def _make_provider_core(
    config: Config,
    *,
    preset: ModelPresetConfig,
    model: str | None = None,
) -> LLMProvider:
    """Create a plain LLM provider without failover wrapping."""
    setup = _resolve_provider_setup(
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
            proxy=getattr(p, "proxy", None) if p else None,
            extra_body=p.extra_body if p else None,
            provider_name=provider_name,
        )
    elif backend == "xai_grok":
        from nanobot.providers.xai_grok_provider import XAIGrokProvider

        provider = XAIGrokProvider(
            default_model=model,
            proxy=getattr(p, "proxy", None) if p else None,
            extra_body=p.extra_body if p else None,
            provider_name=provider_name,
        )
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        if p is None or p.api_base is None:
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
        api_key = p.api_key if p else None
        if custom_spec is not None:
            api_key = api_key or "no-key"
        provider = AnthropicProvider(
            api_key=api_key,
            api_base=config.get_api_base(model, preset=preset),
            default_model=model,
            extra_headers=_provider_extra_headers(spec, p),
            extra_body=p.extra_body if p else None,
            extra_query=p.extra_query if p else None,
            proxy=p.proxy if p else None,
            spec=custom_spec,
            provider_name=provider_name,
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
            provider_name=provider_name,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model, preset=preset),
            default_model=model,
            extra_headers=_provider_extra_headers(spec, p),
            spec=spec,
            extra_body=p.extra_body if p else None,
            api_type=p.api_type if p else "auto",
            model_api=setup.model_api,
            extra_query=p.extra_query if p else None,
            proxy=p.proxy if p else None,
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


def build_unconfigured_provider_snapshot(config: Config, setup_error: str) -> ProviderSnapshot:
    """Build a non-networking runtime so the WebUI can collect first-time setup."""
    from nanobot.providers.unconfigured_provider import UnconfiguredProvider

    preset = config.resolve_preset()
    provider = UnconfiguredProvider(preset.model)
    provider.generation = preset.to_generation_settings()
    return ProviderSnapshot(
        provider=provider,
        model=preset.model,
        context_window_tokens=preset.context_window_tokens,
        signature=("unconfigured", setup_error, preset.model),
        generation=provider.generation,
    )


def provider_signature(
    config: Config,
    *,
    preset_name: str | None = None,
    preset: ModelPresetConfig | None = None,
) -> tuple[object, ...]:
    """Return the config fields that affect the active provider chain."""
    resolved = _resolve_model_preset(config, preset_name=preset_name, preset=preset)
    p = config.get_provider(resolved.model, preset=resolved)
    fallback_presets = _resolve_fallback_presets(config, resolved)

    def _fallback_signature(fallback: ModelPresetConfig) -> tuple[object, ...]:
        fp = config.get_provider(fallback.model, preset=fallback)
        provider_name = config.get_provider_name(fallback.model, preset=fallback)
        return (
            fallback.model,
            fallback.provider,
            provider_name,
            config.get_api_key(fallback.model, preset=fallback),
            config.get_api_base(fallback.model, preset=fallback),
            _provider_extra_headers(find_by_name(provider_name) if provider_name else None, fp),
            fp.extra_body if fp else None,
            fp.api_type if fp else "auto",
            fp.api.model_dump_json() if fp and fp.api is not None else None,
            fp.extra_query if fp else None,
            getattr(fp, "region", None) if fp else None,
            getattr(fp, "profile", None) if fp else None,
            fallback.max_tokens,
            fallback.temperature,
            fallback.reasoning_effort,
            fallback.context_window_tokens,
            fallback.api.model_dump_json() if fallback.api is not None else None,
            getattr(fp, "proxy", None) if fp else None,
            fp.thinking_style if fp else None,
        )

    provider_name = config.get_provider_name(resolved.model, preset=resolved)
    return (
        resolved.model,
        resolved.provider,
        provider_name,
        config.get_api_key(resolved.model, preset=resolved),
        config.get_api_base(resolved.model, preset=resolved),
        _provider_extra_headers(find_by_name(provider_name) if provider_name else None, p),
        p.extra_body if p else None,
        p.api_type if p else "auto",
        p.api.model_dump_json() if p and p.api is not None else None,
        p.extra_query if p else None,
        getattr(p, "region", None) if p else None,
        getattr(p, "profile", None) if p else None,
        resolved.max_tokens,
        resolved.temperature,
        resolved.reasoning_effort,
        resolved.context_window_tokens,
        resolved.api.model_dump_json() if resolved.api is not None else None,
        getattr(p, "proxy", None) if p else None,
        p.thinking_style if p else None,
        tuple(
            fallback if isinstance(fallback, str) else None
            for fallback in config.agents.defaults.fallback_models
        ),
        tuple(_fallback_signature(fallback) for fallback in fallback_presets),
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
