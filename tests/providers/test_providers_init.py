"""Tests for lazy provider exports from nanobot.providers."""

from __future__ import annotations

import importlib
import sys


def test_importing_providers_package_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "nanobot.providers", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.anthropic_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.openai_compat_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.openai_codex_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.azure_openai_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.ollama_provider", raising=False)

    providers = importlib.import_module("nanobot.providers")

    assert "nanobot.providers.anthropic_provider" not in sys.modules
    assert "nanobot.providers.openai_compat_provider" not in sys.modules
    assert "nanobot.providers.openai_codex_provider" not in sys.modules
    assert "nanobot.providers.azure_openai_provider" not in sys.modules
    assert "nanobot.providers.ollama_provider" not in sys.modules
    assert providers.__all__ == [
        "LLMProvider",
        "LLMResponse",
        "AnthropicProvider",
        "OpenAICompatProvider",
        "OpenAICodexProvider",
        "AzureOpenAIProvider",
        "OllamaProvider"
    ]


def test_explicit_provider_import_still_works(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "nanobot.providers", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.anthropic_provider", raising=False)

    namespace: dict[str, object] = {}
    exec("from nanobot.providers import AnthropicProvider", namespace)

    assert namespace["AnthropicProvider"].__name__ == "AnthropicProvider"
    assert "nanobot.providers.anthropic_provider" in sys.modules
