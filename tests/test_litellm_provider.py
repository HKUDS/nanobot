"""Tests for LiteLLMProvider."""

# 模块作用：LiteLLMProvider 的单元测试，验证 Ollama 检测逻辑及其他提供商标志
# 设计目的：确保 is_ollama 属性在各种场景下正确识别本地 Ollama 部署
# 好处：防止回归错误，保障本地 LLM 集成的可靠性，提高代码可维护性
import pytest
from nanobot.providers.litellm_provider import LiteLLMProvider


# 作用：测试 is_ollama 属性的各种场景检测
# 设计目的：覆盖正常情况和边界情况，确保检测逻辑健壮
# 好处：全面验证 Ollama 检测，防止误判或漏判
class TestIsOllama:
    """Test is_ollama property detection."""

    # 作用：测试模型名包含 'ollama' 时正确识别为 Ollama
    # 设计目的：验证最基本的正向检测场景
    # 好处：确保标准 Ollama 模型格式被正确识别
    def test_is_ollama_true_with_ollama_in_model(self):
        """Test is_ollama is True when model contains 'ollama'."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://localhost:11434",
            default_model="ollama/llama3.2"
        )
        assert provider.is_ollama is True

    # 作用：测试模型名包含大写 'OLLAMA' 时也能正确识别
    # 设计目的：验证大小写不敏感的检测逻辑
    # 好处：确保用户输入不同大小写格式都能被正确处理
    def test_is_ollama_true_with_uppercase(self):
        """Test is_ollama is True when model contains 'OLLAMA' (case insensitive)."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://localhost:11434",
            default_model="OLLAMA/llama3.2"
        )
        assert provider.is_ollama is True

    # 作用：测试模型名包含混合大小写 'Ollama' 时的识别
    # 设计目的：验证首字母大写等常见输入格式
    # 好处：提高用户体验，兼容多种输入习惯
    def test_is_ollama_true_with_mixed_case(self):
        """Test is_ollama is True when model contains 'Ollama' (mixed case)."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://localhost:11434",
            default_model="Ollama/llama3.2"
        )
        assert provider.is_ollama is True

    # 作用：测试 api_base 为 None 时不应识别为 Ollama
    # 设计目的：验证 api_base 是必要条件的检测逻辑
    # 好处：防止在没有配置端点的情况下误判为本地 Ollama
    def test_is_ollama_false_without_api_base(self):
        """Test is_ollama is False when api_base is None."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base=None,
            default_model="ollama/llama3.2"
        )
        assert provider.is_ollama is False

    # 作用：测试 api_base 为空字符串时不应识别为 Ollama
    # 设计目的：验证空字符串被视为无效配置
    # 好处：确保空配置不会导致误判，提高健壮性
    def test_is_ollama_false_with_empty_api_base(self):
        """Test is_ollama is False when api_base is empty string."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="",
            default_model="ollama/llama3.2"
        )
        assert provider.is_ollama is False

    # 作用：测试模型名不包含 'ollama' 时不应识别为 Ollama
    # 设计目的：验证负向检测，确保其他模型不被误判
    # 好处：防止将 GPT、Claude 等云模型误判为本地 Ollama
    def test_is_ollama_false_without_ollama_in_model(self):
        """Test is_ollama is False when model doesn't contain 'ollama'."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://localhost:11434",
            default_model="gpt-4"
        )
        assert provider.is_ollama is False

    # 作用：测试使用默认 anthropic 模型时不应识别为 Ollama
    # 设计目的：验证默认配置下不会误判
    # 好处：确保默认行为正确，不影响现有用户
    def test_is_ollama_false_with_default_model(self):
        """Test is_ollama is False with default anthropic model."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://localhost:11434",
            default_model="anthropic/claude-opus-4-5"
        )
        assert provider.is_ollama is False

    # 作用：测试使用 127.0.0.1 地址的典型 Ollama 设置
    # 设计目的：验证本地地址配置的正确识别
    # 好处：覆盖常见的本地部署场景，包括带 /v1 路径的端点
    def test_is_ollama_with_localhost_api_base(self):
        """Test is_ollama with typical Ollama localhost setup."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://127.0.0.1:11434/v1",
            default_model="ollama/mistral"
        )
        assert provider.is_ollama is True

    def test_is_ollama_with_different_ollama_models(self):
        """Test is_ollama with various Ollama model names."""
        test_cases = [
            ("ollama/llama3.2", True),
            ("ollama/mistral", True),
            ("ollama/codellama", True),
            ("ollama/gemma:2b", True),
            ("ollama/phi3", True),
            ("claude-3-opus", False),
            ("gpt-4", False),
            ("gemini-pro", False),
        ]
        
        for model, expected in test_cases:
            provider = LiteLLMProvider(
                api_key="dummy",
                api_base="http://localhost:11434",
                default_model=model
            )
            assert provider.is_ollama == expected, f"Failed for model: {model}"


class TestOtherProviderFlags:
    """Test other provider detection flags for comparison."""

    def test_is_openrouter_detection(self):
        """Test is_openrouter flag."""
        provider = LiteLLMProvider(
            api_key="sk-or-v1-test",
            api_base=None,
            default_model="anthropic/claude-3.5-sonnet"
        )
        assert provider.is_openrouter is True
        assert provider.is_ollama is False

    def test_is_vllm_detection(self):
        """Test is_vllm flag with custom endpoint."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://localhost:8000/v1",
            default_model="meta-llama/Llama-3.1-8B-Instruct"
        )
        assert provider.is_vllm is True
        assert provider.is_ollama is False

    def test_is_aihubmix_detection(self):
        """Test is_aihubmix flag."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="https://aihubmix.com/v1",
            default_model="gpt-4"
        )
        assert provider.is_aihubmix is True
        assert provider.is_ollama is False


# 作用：测试 chat 方法中的 debug 日志输出
# 设计目的：验证第156行的 logger.debug 是否正确记录 LiteLLM 参数
# 好处：确保调试信息可追踪，便于问题排查
class TestChatDebugLogging:
    """Test debug logging in chat method."""

    # 作用：测试 chat 方法调用时输出 debug 日志
    # 设计目的：验证 logger.debug 是否记录关键参数（model, max_tokens, temperature, api_base）
    # 好处：确保调试信息完整，便于排查 LLM 调用问题
    @pytest.mark.asyncio
    async def test_chat_debug_log_output(self, caplog):
        """Test that chat method logs debug info with correct parameters."""
        import logging
        from unittest.mock import patch, AsyncMock
        
        # 设置日志级别为 DEBUG 以捕获 debug 日志
        caplog.set_level(logging.DEBUG, logger="nanobot.providers.litellm_provider")
        
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://localhost:11434",
            default_model="ollama/llama3.2"
        )
        
        messages = [{"role": "user", "content": "Hello"}]
        
        # Mock acompletion 函数以避免实际调用 API
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "Test response"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = None
        
        with patch("nanobot.providers.litellm_provider.acompletion", return_value=mock_response):
            await provider.chat(messages=messages, model="ollama/llama3.2")
        
        # 验证日志中包含关键信息
        assert "LiteLLM param in" in caplog.text
        assert "model: ollama/llama3.2" in caplog.text
   

    # 作用：测试 chat 方法在不同参数下的 debug 日志
    # 设计目的：验证日志记录使用实际传入的参数值
    # 好处：确保日志信息准确反映实际调用情况
    @pytest.mark.asyncio
    async def test_chat_debug_log_with_custom_params(self, caplog):
        """Test debug log with custom max_tokens and temperature."""
        import logging
        from unittest.mock import patch, AsyncMock
        
        caplog.set_level(logging.DEBUG, logger="nanobot.providers.litellm_provider")
        
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://localhost:8000/v1",
            default_model="gpt-4"
        )
        
        messages = [{"role": "user", "content": "Test"}]
        
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "Response"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = None
        
        with patch("nanobot.providers.litellm_provider.acompletion", return_value=mock_response):
            await provider.chat(
                messages=messages,
                model="gpt-4",
                max_tokens=2048,
                temperature=0.5
            )
        
        # 验证日志中包含自定义参数值
        assert "model: gpt-4" in caplog.text