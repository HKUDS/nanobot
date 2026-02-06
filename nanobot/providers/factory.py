"""Provider factory for creating provider instances."""

from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_provider import OpenAIProvider


def create_provider(config: Config) -> LLMProvider:
    """
    Create a provider instance based on configuration.

    Args:
        config: The nanobot configuration.

    Returns:
        An instantiated LLM provider.
    """
    provider_type = config.agents.defaults.provider.lower()
    model = config.agents.defaults.model

    # Use OpenAI SDK if explicitly requested
    if provider_type == "openai":
        # Use OpenAI SDK directly
        # The openai config is used for OpenAI SDK mode
        return OpenAIProvider(
            api_key=config.providers.openai.api_key or None,
            api_base=config.providers.openai.api_base,
            default_model=model
        )
    else:
        # Default to LiteLLM for all other cases (including "litellm" and unknown values)
        return LiteLLMProvider(
            api_key=config.get_api_key(),
            api_base=config.get_api_base(),
            default_model=model
        )
