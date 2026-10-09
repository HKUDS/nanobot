"""Resolve provider connections and request APIs without creating SDK clients."""

from __future__ import annotations

from dataclasses import dataclass

from nanobot.config.schema import Config, ModelAPIConfig, ModelPresetConfig, ProviderConfig
from nanobot.providers.model_api import ModelAPICapabilities, ProviderAPI, RequestAPI
from nanobot.providers.registry import ProviderSpec, create_dynamic_spec, find_by_name


@dataclass(frozen=True)
class ProviderRoute:
    """Validated connection and adapter choice, without constructing a client.

    ``model_api`` carries configured overrides; ``None`` preserves automatic
    model discovery and the adapter's request-time defaults.
    """

    model: str
    provider_name: str
    provider_config: ProviderConfig | None
    spec: ProviderSpec | None
    backend: str
    model_api: ModelAPICapabilities | None


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
        spec = None
    if spec is None and provider_config is not None:
        if not provider_config.api_base:
            raise ValueError(f"Provider '{provider_name}' requires api_base in config.")
        spec = create_dynamic_spec(
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
    connection_api = None
    if provider_config is not None and provider_config.api is not None:
        if not spec.provider_api_configurable:
            raise ValueError(f"Provider '{spec.name}' does not support connection API declarations.")
        connection_api = provider_config.api.to_capabilities()
        spec.validate_model_api(connection_api)
    if preset_api is not None:
        api = preset_api.to_capabilities()
        spec.validate_model_api(api)
        # Built-in OpenAI declares defaults; custom endpoints declare an API ceiling.
        if connection_api is not None and spec.is_direct:
            unsupported = set(api.supported_apis) - set(connection_api.supported_apis)
            if unsupported:
                raise ValueError(
                    f"Provider '{spec.name}' does not accept request APIs: {', '.join(sorted(unsupported))}"
                )
        return api
    if connection_api is None:
        return None
    # Selecting a default adapter does not authorize fallback across API families.
    if connection_api.preferred_api == "anthropic_messages":
        return ModelAPICapabilities(("anthropic_messages",), "anthropic_messages")
    supported: tuple[RequestAPI, ...] = tuple(
        item for item in connection_api.supported_apis if item != "anthropic_messages"
    )
    return ModelAPICapabilities(supported_apis=supported, preferred_api=connection_api.preferred_api)


def resolve_provider_route(
    config: Config,
    *,
    preset: ModelPresetConfig,
    model: str | None = None,
) -> ProviderRoute:
    """Resolve and validate provider configuration without constructing a client."""
    model = model or preset.model
    provider_name = config.get_provider_name(model, preset=preset)
    provider_config = config.get_provider(model, preset=preset)
    if not provider_name:
        raise ValueError(f"No provider is configured for model '{model}'.")
    spec = _provider_spec_for_config(provider_name, provider_config)
    if spec and spec.is_transcription_only:
        raise ValueError(f"Provider '{provider_name}' only supports transcription.")
    backend = spec.backend if spec else "openai_compat"
    model_api = resolve_model_api(spec, provider_config, preset.api) if spec is not None else None
    if model_api is not None and model_api.preferred_api == "anthropic_messages":
        backend = "anthropic"
    if (
        provider_config
        and provider_config.proxy
        and backend not in {"openai_compat", "openai_codex", "xai_grok", "anthropic"}
    ):
        raise ValueError(
            f"providers.{provider_name}.proxy is only supported for "
            "OpenAI-compatible providers, Anthropic Messages, OpenAI Codex, and xAI Grok."
        )

    if backend == "azure_openai":
        if not provider_config or not provider_config.api_base:
            raise ValueError("Azure OpenAI requires api_base in config.")
    elif (
        backend in {"openai_compat", "anthropic"}
        and spec
        and spec.is_direct
        and not spec.default_api_base
        and not (provider_config and provider_config.api_base)
    ):
        raise ValueError(f"Provider '{provider_name}' requires api_base in config.")
    elif backend in {"anthropic", "openai_compat"} and not (
        backend == "openai_compat" and model.startswith("bedrock/")
    ):
        needs_key = not (provider_config and provider_config.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{provider_name}'.")

    return ProviderRoute(
        model=model,
        provider_name=provider_name,
        provider_config=provider_config,
        spec=spec,
        backend=backend,
        model_api=model_api,
    )


def resolve_automatic_model_api(
    config: Config, *, preset: ModelPresetConfig,
) -> tuple[str, ProviderAPI]:
    """Preview the default request API without live requests or circuit-breaker state."""
    setup = resolve_provider_route(config, preset=preset.model_copy(update={"api": None}))
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
    resolved = preset if preset is not None else config.resolve_preset(preset_name)
    resolve_provider_route(
        config,
        preset=resolved,
        model=model,
    )
