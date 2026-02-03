"""LLM provider abstraction module."""

from nanobot.providers.base import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse", "LiteLLMProvider", "LazyLLMProvider"]

# Optional providers: avoid importing hard dependencies at package import time.
try:
    from nanobot.providers.lazyllm_provider import LazyLLMProvider
except Exception:  # pragma: no cover
    LazyLLMProvider = None

try:
    from nanobot.providers.litellm_provider import LiteLLMProvider
except Exception:  # pragma: no cover
    LiteLLMProvider = None
