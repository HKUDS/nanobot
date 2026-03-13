"""Tests for nanobot.providers.registry — provider spec lookup helpers."""

from __future__ import annotations

from nanobot.providers.registry import find_by_model, find_by_name, find_gateway


class TestFindByModel:
    def test_openai_keyword_match(self):
        spec = find_by_model("gpt-4o")
        assert spec is not None
        assert spec.name == "openai"

    def test_anthropic_keyword_match(self):
        spec = find_by_model("claude-3-opus-20240229")
        assert spec is not None
        assert spec.name == "anthropic"

    def test_explicit_prefix_match(self):
        spec = find_by_model("deepseek/deepseek-chat")
        assert spec is not None
        assert spec.name == "deepseek"

    def test_unknown_model_returns_none(self):
        assert find_by_model("totally-unknown-model-xyz") is None


class TestFindGateway:
    def test_by_provider_name(self):
        spec = find_gateway(provider_name="openrouter")
        assert spec is not None
        assert spec.name == "openrouter"

    def test_by_api_key_prefix(self):
        spec = find_gateway(api_key="sk-or-test123")
        assert spec is not None
        assert spec.name == "openrouter"

    def test_by_api_base_keyword(self):
        spec = find_gateway(api_base="https://aihubmix.com/v1")
        assert spec is not None
        assert spec.name == "aihubmix"

    def test_no_match_returns_none(self):
        assert find_gateway() is None

    def test_non_gateway_name_returns_none(self):
        assert find_gateway(provider_name="openai") is None


class TestFindByName:
    def test_known_name(self):
        spec = find_by_name("openai")
        assert spec is not None
        assert spec.name == "openai"

    def test_unknown_name(self):
        assert find_by_name("nonexistent_provider") is None
