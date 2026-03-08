"""Tests for provider registry matching and gateway detection."""

from nanobot.providers.registry import find_by_model, find_gateway


def test_find_by_model_matches_keyword_case_insensitive() -> None:
    """find_by_model should match provider keywords regardless of case."""
    spec = find_by_model("QWEN-MAX")

    assert spec is not None
    assert spec.name == "dashscope"


def test_find_by_model_skips_gateway_provider_keywords() -> None:
    """find_by_model should not return gateway specs matched only by gateway keywords."""
    spec = find_by_model("openrouter-only-model")

    assert spec is None


def test_find_gateway_detects_by_provider_name() -> None:
    """find_gateway should return gateway/local spec when provider_name is explicit."""
    gateway = find_gateway(provider_name="openrouter")
    local = find_gateway(provider_name="vllm")

    assert gateway is not None
    assert gateway.name == "openrouter"
    assert local is not None
    assert local.name == "vllm"


def test_find_gateway_detects_by_api_key_prefix() -> None:
    """find_gateway should detect OpenRouter from the sk-or- api key prefix."""
    spec = find_gateway(api_key="sk-or-example")

    assert spec is not None
    assert spec.name == "openrouter"


def test_find_gateway_detects_by_api_base_keyword() -> None:
    """find_gateway should detect AiHubMix from api_base keyword matching."""
    spec = find_gateway(api_base="https://api.aihubmix.com/v1")

    assert spec is not None
    assert spec.name == "aihubmix"
