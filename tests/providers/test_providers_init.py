"""Tests for lazy provider exports from blackcat.providers."""

from __future__ import annotations

import importlib
import sys


def test_importing_providers_package_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "blackcat.providers", raising=False)
    monkeypatch.delitem(sys.modules, "blackcat.providers.anthropic_provider", raising=False)
    monkeypatch.delitem(sys.modules, "blackcat.providers.openai_compat_provider", raising=False)
    monkeypatch.delitem(sys.modules, "blackcat.providers.openai_codex_provider", raising=False)
    monkeypatch.delitem(sys.modules, "blackcat.providers.github_copilot_provider", raising=False)
    monkeypatch.delitem(sys.modules, "blackcat.providers.azure_openai_provider", raising=False)
    monkeypatch.delitem(sys.modules, "blackcat.providers.bedrock_provider", raising=False)

    providers = importlib.import_module("blackcat.providers")

    assert "blackcat.providers.anthropic_provider" not in sys.modules
    assert "blackcat.providers.openai_compat_provider" not in sys.modules
    assert "blackcat.providers.openai_codex_provider" not in sys.modules
    assert "blackcat.providers.github_copilot_provider" not in sys.modules
    assert "blackcat.providers.azure_openai_provider" not in sys.modules
    assert "blackcat.providers.bedrock_provider" not in sys.modules
    assert providers.__all__ == [
        "LLMProvider",
        "LLMResponse",
        "AnthropicProvider",
        "OpenAICompatProvider",
        "OpenAICodexProvider",
        "GitHubCopilotProvider",
        "AzureOpenAIProvider",
        "BedrockProvider",
    ]


def test_explicit_provider_import_still_works(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "blackcat.providers", raising=False)
    monkeypatch.delitem(sys.modules, "blackcat.providers.anthropic_provider", raising=False)

    namespace: dict[str, object] = {}
    exec("from blackcat.providers import AnthropicProvider", namespace)

    assert namespace["AnthropicProvider"].__name__ == "AnthropicProvider"
    assert "blackcat.providers.anthropic_provider" in sys.modules


def test_openai_codex_supports_progress_deltas() -> None:
    from blackcat.providers.openai_codex_provider import OpenAICodexProvider

    assert OpenAICodexProvider.supports_progress_deltas is True
