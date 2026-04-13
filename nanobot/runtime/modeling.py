"""Helpers for resolving and applying the active model configuration."""

from __future__ import annotations

from dataclasses import dataclass

from nanobot.config.schema import Config, ModelProfile, ProviderConfig


@dataclass
class ActiveModelRuntime:
    """Resolved active model settings used by the runtime."""

    profile: ModelProfile
    provider_name: str | None
    provider_config: ProviderConfig | None
    api_key: str | None
    api_base: str | None
    extra_headers: dict[str, str] | None
    max_tokens: int
    context_window_tokens: int
    temperature: float
    reasoning_effort: str | None


_VISION_MODEL_MARKERS = (
    "gpt-4o",
    "gpt-4.1",
    "o4",
    "claude-3",
    "claude-sonnet-4",
    "claude-opus-4",
    "gemini",
    "glm-4.5v",
    "glm-4.6v",
    "glm-4v",
    "qwen-vl",
    "qvq",
    "vision",
    "multimodal",
    "pixtral",
    "llava",
)


def model_supports_vision(model_name: str | None) -> bool:
    """Heuristic check for whether a configured model can accept image input."""
    name = (model_name or "").strip().lower()
    return any(marker in name for marker in _VISION_MODEL_MARKERS)


def find_vision_model_profile(config: Config) -> ModelProfile | None:
    """Return the first enabled configured model that likely supports vision."""
    for profile in config.get_model_profiles():
        if profile.enabled and model_supports_vision(profile.model):
            return profile
    return None


def resolve_active_model_runtime(config: Config) -> ActiveModelRuntime:
    """Resolve the active model profile plus effective runtime settings."""
    profile = config.get_active_model_profile()
    provider_name = config.get_provider_name(profile.model, provider_name=profile.provider)
    provider_config = config.get_provider(profile.model, provider_name=profile.provider)
    return ActiveModelRuntime(
        profile=profile,
        provider_name=provider_name,
        provider_config=provider_config,
        api_key=profile.api_key if profile.api_key else (provider_config.api_key if provider_config else None),
        api_base=config.get_api_base(
            profile.model,
            provider_name=profile.provider,
            profile_api_base=profile.api_base,
        ),
        extra_headers=profile.extra_headers if profile.extra_headers is not None else (provider_config.extra_headers if provider_config else None),
        max_tokens=profile.max_tokens if profile.max_tokens is not None else config.agents.defaults.max_tokens,
        context_window_tokens=(
            profile.context_window_tokens
            if profile.context_window_tokens is not None
            else config.agents.defaults.context_window_tokens
        ),
        temperature=profile.temperature if profile.temperature is not None else config.agents.defaults.temperature,
        reasoning_effort=(
            profile.reasoning_effort
            if profile.reasoning_effort is not None
            else config.agents.defaults.reasoning_effort
        ),
    )


def make_provider(config: Config):
    """Create a provider instance for the active model profile."""
    from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.gemini_oauth_provider import GeminiOAuthProvider
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
    from nanobot.providers.registry import find_by_name

    runtime = resolve_active_model_runtime(config)
    profile = runtime.profile
    provider_name = runtime.provider_name
    provider_cfg = runtime.provider_config

    if provider_name == "openai_codex" or profile.model.startswith("openai-codex/"):
        provider = OpenAICodexProvider(default_model=profile.model)
    elif provider_name == "gemini_oauth" or profile.model.startswith("gemini-oauth/"):
        provider = GeminiOAuthProvider(
            default_model=profile.model,
            api_base=runtime.api_base,
        )
    elif provider_name == "custom":
        from nanobot.providers.custom_provider import CustomProvider

        provider = CustomProvider(
            api_key=runtime.api_key or "no-key",
            api_base=runtime.api_base or "http://localhost:8000/v1",
            default_model=profile.model,
            extra_headers=runtime.extra_headers,
        )
    elif provider_name == "azure_openai":
        if not runtime.api_key or not runtime.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base.")
        provider = AzureOpenAIProvider(
            api_key=runtime.api_key,
            api_base=runtime.api_base,
            default_model=profile.model,
        )
    else:
        from nanobot.providers.litellm_provider import LiteLLMProvider

        spec = find_by_name(provider_name)
        if (
            not profile.model.startswith("bedrock/")
            and not runtime.api_key
            and not (spec and (spec.is_oauth or spec.is_local))
        ):
            raise ValueError("No API key configured.")
        provider = LiteLLMProvider(
            api_key=runtime.api_key,
            api_base=runtime.api_base,
            default_model=profile.model,
            extra_headers=runtime.extra_headers,
            provider_name=provider_name,
        )

    provider.generation = GenerationSettings(
        temperature=runtime.temperature,
        max_tokens=runtime.max_tokens,
        reasoning_effort=runtime.reasoning_effort,
    )
    return provider, runtime
