"""Provider credentials must not leak through process-global os.environ."""

from __future__ import annotations

import os

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


def test_provider_init_does_not_mutate_shared_env_keys(monkeypatch) -> None:
    """Multi-provider setups must not overwrite or pin each other's keys."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    openai_spec = find_by_name("openai")
    openrouter_spec = find_by_name("openrouter")
    assert openai_spec is not None and openrouter_spec is not None

    OpenAICompatProvider(
        api_key="sk-openai-secret",
        default_model="gpt-4o",
        spec=openai_spec,
    )
    OpenAICompatProvider(
        api_key="sk-or-secret",
        default_model="openrouter/auto",
        spec=openrouter_spec,
        api_base="https://openrouter.ai/api/v1",
    )

    assert "OPENAI_API_KEY" not in os.environ
    assert "OPENROUTER_API_KEY" not in os.environ


def test_provider_init_preserves_preexisting_env_keys(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "preexisting-user-key")

    openai_spec = find_by_name("openai")
    assert openai_spec is not None
    provider = OpenAICompatProvider(
        api_key="sk-from-config",
        default_model="gpt-4o",
        spec=openai_spec,
    )

    assert os.environ["OPENAI_API_KEY"] == "preexisting-user-key"
    assert provider._api_key_for_client == "sk-from-config"
