import os
import pytest
from nanobot.providers.litellm_provider import LiteLLMProvider

def test_zhipu_provider_env_vars():
    # Clear existing env vars
    for key in ["ZAI_API_KEY", "ZHIPUAI_API_KEY", "ZAI_API_BASE", "ZHIPUAI_API_BASE"]:
        if key in os.environ:
            del os.environ[key]
            
    api_key = "test-key"
    api_base = "https://test.api.z.ai/v4"
    
    # Test with zai prefix
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model="zai/glm-4"
    )
    
    assert os.environ.get("ZAI_API_KEY") == api_key
    assert os.environ.get("ZHIPUAI_API_KEY") == api_key
    assert os.environ.get("ZAI_API_BASE") == api_base
    assert os.environ.get("ZHIPUAI_API_BASE") == api_base

def test_zhipu_provider_model_prefixing():
    provider = LiteLLMProvider(
        api_key="test-key",
        default_model="glm-4"
    )
    
    # We need to mock acompletion to test the model prefixing in chat
    # But we can also test the logic by calling a private method if it existed, 
    # or just trust the logic if we can't easily mock.
    # Let's try to mock litellm.acompletion
    
    import asyncio
    from unittest.mock import AsyncMock, patch
    
    with patch("nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value.choices = [AsyncMock()]
        mock_acompletion.return_value.choices[0].message.content = "test"
        mock_acompletion.return_value.choices[0].finish_reason = "stop"
        mock_acompletion.return_value.usage.prompt_tokens = 1
        mock_acompletion.return_value.usage.completion_tokens = 1
        mock_acompletion.return_value.usage.total_tokens = 2
        
        asyncio.run(provider.chat(messages=[{"role": "user", "content": "hi"}]))
        
        # Check if model was prefixed with zai/
        args, kwargs = mock_acompletion.call_args
        assert kwargs["model"] == "zai/glm-4"

def test_zhipu_provider_no_double_prefixing():
    provider = LiteLLMProvider(
        api_key="test-key",
        default_model="zai/glm-4"
    )
    
    import asyncio
    from unittest.mock import AsyncMock, patch
    
    with patch("nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value.choices = [AsyncMock()]
        mock_acompletion.return_value.choices[0].message.content = "test"
        mock_acompletion.return_value.choices[0].finish_reason = "stop"
        mock_acompletion.return_value.usage.prompt_tokens = 1
        mock_acompletion.return_value.usage.completion_tokens = 1
        mock_acompletion.return_value.usage.total_tokens = 2
        
        asyncio.run(provider.chat(messages=[{"role": "user", "content": "hi"}]))
        
        # Check if model was NOT double prefixed
        args, kwargs = mock_acompletion.call_args
        assert kwargs["model"] == "zai/glm-4"
