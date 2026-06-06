"""LLM provider abstraction module."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from nanobot.providers.base import LLMProvider, LLMResponse

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "AnthropicProvider",
    "OpenAICompatProvider",
    "OpenAICodexProvider",
    "GitHubCopilotProvider",
    "XaiOAuthProvider",
    "AzureOpenAIProvider",
    "BedrockProvider",
]

_LAZY_IMPORTS = {
    "AnthropicProvider": ".anthropic_provider",
    "OpenAICompatProvider": ".openai_compat_provider",
    "OpenAICodexProvider": ".openai_codex_provider",
    "GitHubCopilotProvider": ".github_copilot_provider",
    "XaiOAuthProvider": ".xai_oauth_provider",
    "AzureOpenAIProvider": ".azure_openai_provider",
    "BedrockProvider": ".bedrock_provider",
}

_LAZY_SUBMODULES = {
    "anthropic_provider": ".anthropic_provider",
    "openai_compat_provider": ".openai_compat_provider",
    "openai_codex_provider": ".openai_codex_provider",
    "github_copilot_provider": ".github_copilot_provider",
    "xai_oauth_provider": ".xai_oauth_provider",
    "azure_openai_provider": ".azure_openai_provider",
    "bedrock_provider": ".bedrock_provider",
    "factory": ".factory",
    "registry": ".registry",
}

if TYPE_CHECKING:
    from nanobot.providers.anthropic_provider import AnthropicProvider
    from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
    from nanobot.providers.bedrock_provider import BedrockProvider
    from nanobot.providers.github_copilot_provider import GitHubCopilotProvider
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
    from nanobot.providers.xai_oauth_provider import XaiOAuthProvider


def __getattr__(name: str):
    """Lazily expose provider implementations without importing all backends up front."""
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is not None:
        module = import_module(module_name, __name__)
        return getattr(module, name)
    module_name = _LAZY_SUBMODULES.get(name)
    if module_name is not None:
        module = import_module(module_name, __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
