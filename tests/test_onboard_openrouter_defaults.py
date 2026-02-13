from nanobot.cli.commands import (
    OPENROUTER_DEFAULT_EXTRA_HEADERS,
    _make_provider,
    _resolve_runtime_extra_headers,
    _seed_openrouter_attribution_headers,
)
from nanobot.config.schema import Config
import pytest


def test_do_not_override_intentionally_empty_openrouter_headers() -> None:
    config = Config()
    config.providers.openrouter.extra_headers = {}

    _seed_openrouter_attribution_headers(config)

    assert config.providers.openrouter.extra_headers == {}


@pytest.mark.parametrize(
    ("extra_headers", "expected"),
    [
        (None, OPENROUTER_DEFAULT_EXTRA_HEADERS),
        ({}, {}),
    ],
)
def test_runtime_fallback_handles_unset_and_explicit_empty(
    extra_headers: dict[str, str] | None, expected: dict[str, str]
) -> None:
    resolved = _resolve_runtime_extra_headers("openrouter", extra_headers)

    assert resolved == expected


def test_make_provider_applies_openrouter_runtime_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class DummyProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("nanobot.providers.litellm_provider.LiteLLMProvider", DummyProvider)

    config = Config()
    config.providers.openrouter.api_key = "sk-test"
    config.providers.openrouter.extra_headers = None
    config.agents.defaults.model = "openrouter/anthropic/claude-opus-4-5"

    _make_provider(config)

    assert captured["provider_name"] == "openrouter"
    assert captured["extra_headers"] == OPENROUTER_DEFAULT_EXTRA_HEADERS
