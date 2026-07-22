"""Tests for lazy provider exports from nanobot.providers."""

from __future__ import annotations

import importlib
import sys


def test_importing_providers_package_is_lazy(monkeypatch) -> None:
    original_package = sys.modules["nanobot.providers"]
    monkeypatch.delitem(sys.modules, "nanobot.providers", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.anthropic_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.openai_compat_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.openai_codex_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.xai_oauth", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.xai_oauth_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.github_copilot_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.azure_openai_provider", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.bedrock_provider", raising=False)

    try:
        providers = importlib.import_module("nanobot.providers")

        assert "nanobot.providers.anthropic_provider" not in sys.modules
        assert "nanobot.providers.openai_compat_provider" not in sys.modules
        assert "nanobot.providers.openai_codex_provider" not in sys.modules
        assert "nanobot.providers.xai_oauth" not in sys.modules
        assert "nanobot.providers.xai_oauth_provider" not in sys.modules
        assert "nanobot.providers.github_copilot_provider" not in sys.modules
        assert "nanobot.providers.azure_openai_provider" not in sys.modules
        assert "nanobot.providers.bedrock_provider" not in sys.modules
        assert providers.__all__ == [
            "LLMProvider",
            "LLMResponse",
            "AnthropicProvider",
            "OpenAICompatProvider",
            "OpenAICodexProvider",
            "XAIOAuthProvider",
            "GitHubCopilotProvider",
            "AzureOpenAIProvider",
            "BedrockProvider",
        ]
    finally:
        # Importing a replacement subpackage also replaces nanobot.providers on the
        # parent package. Restore both views so this isolation test cannot pollute
        # later tests that resolve a module through a dotted monkeypatch target.
        monkeypatch.undo()
        setattr(sys.modules["nanobot"], "providers", original_package)


def test_explicit_provider_import_still_works(monkeypatch) -> None:
    original_package = sys.modules["nanobot.providers"]
    monkeypatch.delitem(sys.modules, "nanobot.providers", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.anthropic_provider", raising=False)

    try:
        namespace: dict[str, object] = {}
        exec("from nanobot.providers import AnthropicProvider", namespace)

        assert namespace["AnthropicProvider"].__name__ == "AnthropicProvider"
        assert "nanobot.providers.anthropic_provider" in sys.modules
    finally:
        monkeypatch.undo()
        setattr(sys.modules["nanobot"], "providers", original_package)


def test_openai_codex_supports_progress_deltas() -> None:
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider

    assert OpenAICodexProvider.supports_progress_deltas is True
