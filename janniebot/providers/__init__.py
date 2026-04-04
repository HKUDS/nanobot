"""LLM provider abstraction module."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from janniebot.providers.base import LLMProvider, LLMResponse

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "AnthropicProvider",
    "OpenAICompatProvider",
    "OpenAICodexProvider",
    "GitHubCopilotProvider",
    "AzureOpenAIProvider",
]

_LAZY_IMPORTS = {
    "AnthropicProvider": ".anthropic_provider",
    "OpenAICompatProvider": ".openai_compat_provider",
    "OpenAICodexProvider": ".openai_codex_provider",
    "GitHubCopilotProvider": ".github_copilot_provider",
    "AzureOpenAIProvider": ".azure_openai_provider",
}

if TYPE_CHECKING:
    from janniebot.providers.anthropic_provider import AnthropicProvider
    from janniebot.providers.azure_openai_provider import AzureOpenAIProvider
    from janniebot.providers.github_copilot_provider import GitHubCopilotProvider
    from janniebot.providers.openai_codex_provider import OpenAICodexProvider
    from janniebot.providers.openai_compat_provider import OpenAICompatProvider


def __getattr__(name: str):
    """Lazily expose provider implementations without importing all backends up front."""
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    return getattr(module, name)
