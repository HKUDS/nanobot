"""Tests for the provider registry (ProviderSpec, lookup helpers)."""

from blackcat.providers.registry import (
    PROVIDERS,
    ProviderSpec,
    find_by_name,
)

# ── find_by_name ───────────────────────────────────────────────────


def test_find_by_name_anthropic():
    spec = find_by_name("anthropic")
    assert spec is not None
    assert spec.env_key == "ANTHROPIC_API_KEY"


def test_find_by_name_openai():
    spec = find_by_name("openai")
    assert spec is not None
    assert spec.env_key == "OPENAI_API_KEY"


def test_find_by_name_groq():
    spec = find_by_name("groq")
    assert spec is not None
    assert spec.env_key == "GROQ_API_KEY"


def test_find_by_name_unknown():
    assert find_by_name("nonexistent") is None


# ── ProviderSpec properties ────────────────────────────────────────


def test_label_uses_display_name():
    spec = find_by_name("openrouter")
    assert spec is not None
    assert spec.label == "OpenRouter"


def test_label_falls_back_to_title():
    spec = ProviderSpec(name="test", keywords=("test",), env_key="TEST_KEY")
    assert spec.label == "Test"


def test_providers_tuple_is_not_empty():
    assert len(PROVIDERS) > 0


def test_all_providers_have_unique_names():
    names = [spec.name for spec in PROVIDERS]
    assert len(names) == len(set(names))


def test_moonshot_model_overrides():
    spec = find_by_name("moonshot")
    assert spec is not None
    overrides = dict(spec.model_overrides)
    assert "kimi-k2.5" in overrides
    assert overrides["kimi-k2.5"]["temperature"] == 1.0


def test_anthropic_supports_prompt_caching():
    spec = find_by_name("anthropic")
    assert spec is not None
    assert spec.supports_prompt_caching is True


def test_openrouter_is_gateway():
    spec = find_by_name("openrouter")
    assert spec is not None
    assert spec.is_gateway is True


def test_vllm_is_local():
    spec = find_by_name("vllm")
    assert spec is not None
    assert spec.is_local is True


def test_openrouter_strip_model_prefix():
    spec = find_by_name("openrouter")
    assert spec is not None
    assert spec.strip_model_prefix is False
