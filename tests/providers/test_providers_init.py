"""Tests for lazy provider exports from janniebot.providers."""

from __future__ import annotations

import importlib
import sys


def test_importing_providers_package_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "janniebot.providers", raising=False)
    monkeypatch.delitem(sys.modules, "janniebot.providers.anthropic_provider", raising=False)
    monkeypatch.delitem(sys.modules, "janniebot.providers.openai_compat_provider", raising=False)
    monkeypatch.delitem(sys.modules, "janniebot.providers.openai_codex_provider", raising=False)
    monkeypatch.delitem(sys.modules, "janniebot.providers.github_copilot_provider", raising=False)
    monkeypatch.delitem(sys.modules, "janniebot.providers.azure_openai_provider", raising=False)

    providers = importlib.import_module("janniebot.providers")

    assert "janniebot.providers.anthropic_provider" not in sys.modules
    assert "janniebot.providers.openai_compat_provider" not in sys.modules
    assert "janniebot.providers.openai_codex_provider" not in sys.modules
    assert "janniebot.providers.github_copilot_provider" not in sys.modules
    assert "janniebot.providers.azure_openai_provider" not in sys.modules
    assert providers.__all__ == [
        "LLMProvider",
        "LLMResponse",
        "AnthropicProvider",
        "OpenAICompatProvider",
        "OpenAICodexProvider",
        "GitHubCopilotProvider",
        "AzureOpenAIProvider",
    ]


def test_explicit_provider_import_still_works(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "janniebot.providers", raising=False)
    monkeypatch.delitem(sys.modules, "janniebot.providers.anthropic_provider", raising=False)

    namespace: dict[str, object] = {}
    exec("from janniebot.providers import AnthropicProvider", namespace)

    assert namespace["AnthropicProvider"].__name__ == "AnthropicProvider"
    assert "janniebot.providers.anthropic_provider" in sys.modules
