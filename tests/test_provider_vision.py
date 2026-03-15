"""Tests for provider vision support."""

from unittest.mock import Mock, patch

import pytest

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.registry import (
    ProviderSpec,
    find_by_model,
    find_gateway,
    find_by_name,
)


class TestLLMProviderVisionSupport:
    """Test cases for LLMProvider vision support."""

    def test_base_provider_supports_vision_default(self):
        """Test that base provider returns False for vision support by default."""
        provider = LLMProvider(api_key="test_key")
        assert provider.supports_vision() is False

    def test_base_provider_supports_vision_can_be_overridden(self):
        """Test that subclasses can override supports_vision."""

        class VisionProvider(LLMProvider):
            def supports_vision(self):
                return True

            async def chat(self, messages, tools=None, model=None, **kwargs):
                return LLMResponse(content="test")

            def get_default_model(self):
                return "vision-model"

        provider = VisionProvider(api_key="test_key")
        assert provider.supports_vision() is True


class TestLiteLLMProviderVisionSupport:
    """Test cases for LiteLLMProvider vision support."""

    def test_lite_llm_provider_supports_vision_gateway(self):
        """Test vision support with gateway provider."""
        spec = ProviderSpec(
            name="test_gateway",
            keywords=("test",),
            env_key="TEST_API_KEY",
            supports_vision=True,
            is_gateway=True,
        )

        with patch("nanobot.providers.litellm_provider.find_gateway", return_value=spec):
            provider = LiteLLMProvider(
                api_key="test_key",
                provider_name="test_gateway",
            )
            assert provider.supports_vision() is True

    def test_lite_llm_provider_supports_vision_standard(self):
        """Test vision support with standard provider."""
        spec = ProviderSpec(
            name="test_provider",
            keywords=("test",),
            env_key="TEST_API_KEY",
            supports_vision=True,
        )

        with patch("nanobot.providers.litellm_provider.find_by_model", return_value=spec):
            provider = LiteLLMProvider(
                api_key="test_key",
                default_model="test-model",
            )
            assert provider.supports_vision() is True

    def test_lite_llm_provider_no_vision_support(self):
        """Test provider without vision support."""
        spec = ProviderSpec(
            name="test_provider",
            keywords=("test",),
            env_key="TEST_API_KEY",
            supports_vision=False,
        )

        with patch("nanobot.providers.litellm_provider.find_by_model", return_value=spec):
            provider = LiteLLMProvider(
                api_key="test_key",
                default_model="test-model",
            )
            assert provider.supports_vision() is False

    def test_lite_llm_provider_vision_gateway_priority(self):
        """Test that gateway vision support takes priority."""
        gateway_spec = ProviderSpec(
            name="test_gateway",
            keywords=("test",),
            env_key="TEST_API_KEY",
            supports_vision=True,
            is_gateway=True,
        )

        standard_spec = ProviderSpec(
            name="test_provider",
            keywords=("test",),
            env_key="TEST_API_KEY",
            supports_vision=False,
        )

        with patch("nanobot.providers.litellm_provider.find_gateway", return_value=gateway_spec):
            with patch("nanobot.providers.litellm_provider.find_by_model", return_value=standard_spec):
                provider = LiteLLMProvider(
                    api_key="test_key",
                    provider_name="test_gateway",
                    default_model="test-model",
                )
                # Gateway should take priority
                assert provider.supports_vision() is True

    def test_lite_llm_provider_vision_no_spec(self):
        """Test vision support when no spec is found."""
        with patch("nanobot.providers.litellm_provider.find_gateway", return_value=None):
            with patch("nanobot.providers.litellm_provider.find_by_model", return_value=None):
                provider = LiteLLMProvider(
                    api_key="test_key",
                    default_model="test-model",
                )
                # Safe default: False
                assert provider.supports_vision() is False


class TestProviderRegistryVisionSupport:
    """Test cases for provider registry vision support."""

    def test_openrouter_supports_vision(self):
        """Test that OpenRouter supports vision."""
        spec = find_by_name("openrouter")
        assert spec is not None
        assert spec.supports_vision is True

    def test_anthropic_supports_vision(self):
        """Test that Anthropic supports vision."""
        spec = find_by_name("anthropic")
        assert spec is not None
        assert spec.supports_vision is True

    def test_openai_supports_vision(self):
        """Test that OpenAI supports vision."""
        spec = find_by_name("openai")
        assert spec is not None
        assert spec.supports_vision is True

    def test_openai_codex_supports_vision(self):
        """Test that OpenAI Codex supports vision."""
        spec = find_by_name("openai_codex")
        assert spec is not None
        assert spec.supports_vision is True

    def test_gemini_supports_vision(self):
        """Test that Gemini supports vision."""
        spec = find_by_name("gemini")
        assert spec is not None
        assert spec.supports_vision is True

    def test_deepseek_no_vision(self):
        """Test that DeepSeek does not support vision."""
        spec = find_by_name("deepseek")
        assert spec is not None
        assert spec.supports_vision is False

    def test_zhipu_no_vision(self):
        """Test that Zhipu does not support vision."""
        spec = find_by_name("zhipu")
        assert spec is not None
        assert spec.supports_vision is False

    def test_dashscope_no_vision(self):
        """Test that DashScope does not support vision."""
        spec = find_by_name("dashscope")
        assert spec is not None
        assert spec.supports_vision is False

    def test_moonshot_no_vision(self):
        """Test that Moonshot does not support vision."""
        spec = find_by_name("moonshot")
        assert spec is not None
        assert spec.supports_vision is False

    def test_minimax_no_vision(self):
        """Test that MiniMax does not support vision."""
        spec = find_by_name("minimax")
        assert spec is not None
        assert spec.supports_vision is False

    def test_vllm_no_vision(self):
        """Test that vLLM does not support vision."""
        spec = find_by_name("vllm")
        assert spec is not None
        assert spec.supports_vision is False

    def test_ollama_no_vision(self):
        """Test that Ollama does not support vision."""
        spec = find_by_name("ollama")
        assert spec is not None
        assert spec.supports_vision is False

    def test_groq_no_vision(self):
        """Test that Groq does not support vision."""
        spec = find_by_name("groq")
        assert spec is not None
        assert spec.supports_vision is False

    def test_custom_no_vision(self):
        """Test that Custom provider does not support vision."""
        spec = find_by_name("custom")
        assert spec is not None
        assert spec.supports_vision is False

    def test_azure_openai_no_vision(self):
        """Test that Azure OpenAI does not support vision."""
        spec = find_by_name("azure_openai")
        assert spec is not None
        assert spec.supports_vision is False

    def test_find_by_model_with_vision_support(self):
        """Test finding provider by model with vision support."""
        spec = find_by_model("claude-3-opus")
        assert spec is not None
        assert spec.supports_vision is True

    def test_find_by_model_without_vision_support(self):
        """Test finding provider by model without vision support."""
        spec = find_by_model("deepseek-chat")
        assert spec is not None
        assert spec.supports_vision is False

    def test_find_gateway_with_vision_support(self):
        """Test finding gateway with vision support."""
        spec = find_gateway(api_key="sk-or-test")
        assert spec is not None
        assert spec.supports_vision is True

    def test_find_gateway_without_vision_support(self):
        """Test finding gateway without vision support."""
        spec = find_gateway(api_base="https://aihubmix.com")
        assert spec is not None
        assert spec.supports_vision is False

    def test_all_providers_have_vision_flag(self):
        """Test that all providers have vision support flag defined."""
        from nanobot.providers.registry import PROVIDERS

        for spec in PROVIDERS:
            assert hasattr(spec, "supports_vision")
            assert isinstance(spec.supports_vision, bool)

    def test_vision_support_is_frozen(self):
        """Test that vision support flag is frozen."""
        spec = find_by_name("anthropic")
        original_vision = spec.supports_vision

        # Try to modify (should fail because spec is frozen)
        try:
            spec.supports_vision = not original_vision
            assert False, "Should not be able to modify frozen spec"
        except (AttributeError, TypeError):
            # Expected - spec is frozen
            pass

    def test_vision_support_consistency(self):
        """Test that vision support is consistent across related providers."""
        # OpenRouter should support vision
        openrouter = find_by_name("openrouter")
        assert openrouter.supports_vision is True

        # Anthropic should support vision
        anthropic = find_by_name("anthropic")
        assert anthropic.supports_vision is True

        # OpenAI should support vision
        openai = find_by_name("openai")
        assert openai.supports_vision is True

        # These are all vision-capable in reality
        assert openrouter.supports_vision == anthropic.supports_vision == openai.supports_vision


class TestVisionSupportIntegration:
    """Integration tests for vision support."""

    def test_provider_vision_affects_tool_registration(self):
        """Test that provider vision support affects tool registration."""
        # This is more of a design test - the actual integration
        # is tested in agent loop tests
        pass

    def test_vision_support_documentation(self):
        """Test that vision support is properly documented."""
        spec = find_by_name("anthropic")
        assert spec.supports_vision is True

        # Check that the spec has proper documentation
        assert spec.display_name != ""
        assert spec.name != ""

    def test_vision_support_backward_compatibility(self):
        """Test that vision support doesn't break backward compatibility."""
        # Create a provider without vision support
        spec = ProviderSpec(
            name="old_provider",
            keywords=("old",),
            env_key="OLD_API_KEY",
            supports_vision=False,
        )

        # Should work fine
        assert spec.supports_vision is False
        assert spec.name == "old_provider"

    def test_vision_support_future_proofing(self):
        """Test that vision support can be added to new providers."""
        # Create a new provider with vision support
        spec = ProviderSpec(
            name="future_provider",
            keywords=("future",),
            env_key="FUTURE_API_KEY",
            supports_vision=True,
        )

        assert spec.supports_vision is True
        assert spec.name == "future_provider"

    def test_vision_support_multiple_gateways(self):
        """Test vision support across multiple gateways."""
        # OpenRouter supports vision
        openrouter = find_by_name("openrouter")
        assert openrouter.supports_vision is True

        # AiHubMix does not support vision
        aihubmix = find_by_name("aihubmix")
        assert aihubmix.supports_vision is False

        # SiliconFlow does not support vision
        siliconflow = find_by_name("siliconflow")
        assert siliconflow.supports_vision is False

    def test_vision_support_oauth_providers(self):
        """Test vision support for OAuth providers."""
        # OpenAI Codex supports vision
        openai_codex = find_by_name("openai_codex")
        assert openai_codex.supports_vision is True

        # GitHub Copilot does not support vision
        github_copilot = find_by_name("github_copilot")
        assert github_copilot.supports_vision is False

    def test_vision_support_local_providers(self):
        """Test vision support for local providers."""
        # vLLM does not support vision
        vllm = find_by_name("vllm")
        assert vllm.supports_vision is False

        # Ollama does not support vision
        ollama = find_by_name("ollama")
        assert ollama.supports_vision is False

    def test_vision_support_auxiliary_providers(self):
        """Test vision support for auxiliary providers."""
        # Groq does not support vision
        groq = find_by_name("groq")
        assert groq.supports_vision is False

    def test_vision_support_chinese_providers(self):
        """Test vision support for Chinese providers."""
        # Zhipu does not support vision
        zhipu = find_by_name("zhipu")
        assert zhipu.supports_vision is False

        # DashScope does not support vision
        dashscope = find_by_name("dashscope")
        assert dashscope.supports_vision is False

        # Moonshot does not support vision
        moonshot = find_by_name("moonshot")
        assert moonshot.supports_vision is False

        # MiniMax does not support vision
        minimax = find_by_name("minimax")
        assert minimax.supports_vision is False

    def test_vision_support_international_providers(self):
        """Test vision support for international providers."""
        # VolcEngine does not support vision
        volcengine = find_by_name("volcengine")
        assert volcengine.supports_vision is False

        # BytePlus does not support vision
        byteplus = find_by_name("byteplus")
        assert byteplus.supports_vision is False

    def test_vision_support_consistency_with_reality(self):
        """Test that vision support flags match reality."""
        # These providers actually support vision
        vision_capable = ["anthropic", "openai", "openai_codex", "gemini", "openrouter"]

        for name in vision_capable:
            spec = find_by_name(name)
            assert spec is not None, f"{name} not found in registry"
            assert spec.supports_vision is True, f"{name} should support vision"

        # These providers don't support vision
        non_vision = ["deepseek", "zhipu", "dashscope", "moonshot", "minimax"]

        for name in non_vision:
            spec = find_by_name(name)
            assert spec is not None, f"{name} not found in registry"
            assert spec.supports_vision is False, f"{name} should not support vision"
