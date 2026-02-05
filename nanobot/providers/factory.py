"""Provider factory - Convention over Configuration.

DEFAULT: All models use OpenAI-compatible protocol.
EXCEPTION: Models with "@anthropic/" or "@gemini/" prefix use native SDKs.

Configuration:
- openai: OpenAI-compatible provider config (default)
- anthropic: Anthropic native SDK config (for "@anthropic/" prefix)
- gemini: Gemini native SDK config (for "@gemini/" prefix)

Note: Using "@" prefix avoids conflicts with vendor model names like
OpenRouter's "anthropic/claude-opus-4-5" or SiliconFlow's prefixes.
"""

from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider
from nanobot.providers.openai_provider import OpenAIProvider
from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.gemini_provider import GeminiProvider


# Default timeout for API requests (seconds)
DEFAULT_TIMEOUT = 120

# Indicators for local/deployment models (no API key required)
LOCAL_MODEL_INDICATORS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "ollama",
    "vllm",
    "lm-studio",
    "lmstudio",
)


class ProviderConfigError(Exception):
    """Raised when provider configuration is invalid."""
    pass


# Native SDK providers (non-OpenAI protocol)
NATIVE_SDK_PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}

# Model prefixes that indicate native SDK usage
# Using "@" avoids conflicts with vendor prefixes (OpenRouter, SiliconFlow, etc.)
NATIVE_PROVIDER_PREFIXES: dict[str, str] = {
    "anthropic": "@anthropic/",
    "gemini": "@gemini/",
}


def create_provider(config: Config) -> LLMProvider:
    """
    Create LLM provider using convention over configuration.

    Convention:
    - Default: OpenAI-compatible protocol (covers 50+ providers)
    - Exception: "@anthropic/" prefix → Anthropic native SDK
    - Exception: "@gemini/" prefix → Gemini native SDK

    Args:
        config: The nanobot configuration.

    Returns:
        An LLM provider instance.

    Raises:
        ProviderConfigError: If required API key is missing.
    """
    model = config.agents.defaults.model
    api_base = config.get_api_base()

    # Detect provider type from model prefix
    provider_type, clean_model = _parse_model_name(model)

    if provider_type in NATIVE_SDK_PROVIDERS:
        # Use native SDK
        provider_class = NATIVE_SDK_PROVIDERS[provider_type]
        provider_key = _get_provider_key(config, provider_type)

        if not provider_key:
            raise ProviderConfigError(
                f"Provider '{provider_type}' requires API key. "
                f"Set {provider_type}.apiKey in config."
            )

        return provider_class(
            api_key=provider_key,
            api_base=api_base,
            default_model=clean_model,
            timeout=DEFAULT_TIMEOUT,
        )

    # Default: OpenAI-compatible protocol
    provider_key = config.get_api_key()

    if not provider_key and not _is_local_model(model, api_base):
        raise ProviderConfigError(
            "No API key configured. Set openai.apiKey in config."
        )

    return OpenAIProvider(
        api_key=provider_key,
        api_base=api_base,
        default_model=model,
        timeout=DEFAULT_TIMEOUT,
    )


def _parse_model_name(model: str) -> tuple[str | None, str]:
    """
    Parse model name to detect provider prefix.

    Args:
        model: Model name to parse.

    Returns:
        (provider_type, clean_model_name)

    Examples:
        "@anthropic/claude-opus-4-5" → ("anthropic", "claude-opus-4-5")
        "@gemini/gemini-2.5-flash"   → ("gemini", "gemini-2.5-flash")
        "gpt-4o"                     → (None, "gpt-4o")
        "anthropic/claude-opus-4-5"   → (None, "anthropic/claude-opus-4-5")  # OpenRouter format
    """
    for provider_type, prefix in NATIVE_PROVIDER_PREFIXES.items():
        if model.startswith(prefix):
            clean_model = model.removeprefix(prefix)
            return provider_type, clean_model

    return None, model


def _get_provider_key(config: Config, provider_type: str) -> str | None:
    """
    Get API key for a specific native provider from config.

    Args:
        config: The nanobot configuration.
        provider_type: Provider type ("anthropic" or "gemini").

    Returns:
        API key if configured, None otherwise.
    """
    # Validate provider_type against known providers
    if provider_type not in NATIVE_SDK_PROVIDERS:
        return None

    # Safely get provider config
    provider = getattr(config, provider_type, None)
    if provider and hasattr(provider, "api_key"):
        return provider.api_key or None
    return None


def _is_local_model(model: str, api_base: str | None) -> bool:
    """
    Check if this is a local model request.

    Args:
        model: Model name.
        api_base: API base URL.

    Returns:
        True if appears to be a local model.
    """
    if api_base:
        return any(
            indicator in api_base.lower()
            for indicator in LOCAL_MODEL_INDICATORS
        )
    return any(
        indicator in model.lower()
        for indicator in LOCAL_MODEL_INDICATORS
    )
