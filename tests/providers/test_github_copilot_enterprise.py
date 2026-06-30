"""Regression tests for GitHub Enterprise / Copilot for Business endpoint overrides (#4220)."""

from __future__ import annotations

from nanobot.providers import github_copilot_provider as gc


def test_resolve_falls_back_to_default_without_env(monkeypatch):
    monkeypatch.delenv("NANOBOT_COPILOT_BASE_URL", raising=False)
    assert gc._resolve("NANOBOT_COPILOT_BASE_URL", gc.DEFAULT_COPILOT_BASE_URL) == (
        gc.DEFAULT_COPILOT_BASE_URL
    )


def test_resolve_uses_env_override_and_strips(monkeypatch):
    monkeypatch.setenv("NANOBOT_COPILOT_TOKEN_URL", "  https://api.acme.ghe.com/copilot_internal/v2/token  ")
    assert gc._resolve("NANOBOT_COPILOT_TOKEN_URL", gc.DEFAULT_COPILOT_TOKEN_URL) == (
        "https://api.acme.ghe.com/copilot_internal/v2/token"
    )


def test_blank_env_override_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("NANOBOT_COPILOT_BASE_URL", "   ")
    assert gc._resolve("NANOBOT_COPILOT_BASE_URL", gc.DEFAULT_COPILOT_BASE_URL) == (
        gc.DEFAULT_COPILOT_BASE_URL
    )


def test_provider_api_base_honors_env_override(monkeypatch):
    monkeypatch.setenv("NANOBOT_COPILOT_BASE_URL", "https://copilot-api.acme.ghe.com")
    provider = gc.GitHubCopilotProvider()
    assert provider.api_base == "https://copilot-api.acme.ghe.com"
