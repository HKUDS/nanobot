"""Provider factory for creating LLM providers based on configuration."""

from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.anthropic_provider import AnthropicProvider


def create_provider(config: Config) -> LLMProvider:
    """
    Create an LLM provider based on configuration.

    Args:
        config: The nanobot configuration.

    Returns:
        An LLM provider instance.
    """
    model = config.agents.defaults.model
    provider_type = config.agents.defaults.provider_type
    api_key = config.get_api_key()
    api_base = config.get_api_base()

    # Determine if we should use native Anthropic provider
    use_native = False
    if provider_type == "native":
        use_native = True
    elif provider_type == "auto":
        # Auto-detect: use native Anthropic provider when:
        # 1. Model name contains "anthropic" or "claude"
        # 2. Anthropic API key is configured
        # 3. Not using OpenRouter
        is_anthropic_model = "anthropic" in model.lower() or "claude" in model.lower()
        has_anthropic_key = bool(config.providers.anthropic.api_key)
        not_openrouter = not config.providers.openrouter.api_key
        not_zhipu = "zhipu" not in model.lower() and "glm" not in model.lower() and "zai" not in model.lower()
        use_native = is_anthropic_model and has_anthropic_key and not_openrouter and not_zhipu

    if use_native:
        # Use native Anthropic provider
        # Strip "anthropic/" prefix if present
        clean_model = model.replace("anthropic/", "") if model.startswith("anthropic/") else model
        return AnthropicProvider(
            api_key=config.providers.anthropic.api_key,
            api_base=api_base,
            default_model=clean_model,
        )

    # Default to LiteLLM provider
    return LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=model,
    )
