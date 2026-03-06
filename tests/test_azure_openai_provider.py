"""Test Azure OpenAI provider implementation (updated for model-based deployment names)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch

from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import LLMResponse


def test_azure_openai_provider_init():
    """Test AzureOpenAIProvider initialization without deployment_name."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o-deployment",
    )
    
    assert provider.api_key == "test-key"
    assert provider.api_base == "https://test-resource.openai.azure.com/"
    assert provider.default_model == "gpt-4o-deployment"
    assert provider.api_version == "2024-10-21"


def test_azure_openai_provider_init_validation():
    """Test AzureOpenAIProvider initialization validation."""
    # Missing api_key
    with pytest.raises(ValueError, match="Azure OpenAI api_key is required"):
        AzureOpenAIProvider(api_key="", api_base="https://test.com")
    
    # Missing api_base
    with pytest.raises(ValueError, match="Azure OpenAI api_base is required"):
        AzureOpenAIProvider(api_key="test", api_base="")


def test_build_chat_url():
    """Test Azure OpenAI URL building with different deployment names."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )
    
    # Test various deployment names
    test_cases = [
        ("gpt-4o-deployment", "https://test-resource.openai.azure.com/openai/deployments/gpt-4o-deployment/chat/completions?api-version=2024-10-21"),
        ("gpt-35-turbo", "https://test-resource.openai.azure.com/openai/deployments/gpt-35-turbo/chat/completions?api-version=2024-10-21"),
        ("custom-model", "https://test-resource.openai.azure.com/openai/deployments/custom-model/chat/completions?api-version=2024-10-21"),
    ]
    
    for deployment_name, expected_url in test_cases:
        url = provider._build_chat_url(deployment_name)
        assert url == expected_url


def test_build_chat_url_api_base_without_slash():
    """Test URL building when api_base doesn't end with slash."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",  # No trailing slash
        default_model="gpt-4o",
    )
    
    url = provider._build_chat_url("test-deployment")
    expected = "https://test-resource.openai.azure.com/openai/deployments/test-deployment/chat/completions?api-version=2024-10-21"
    assert url == expected


def test_build_headers():
    """Test Azure OpenAI header building with api-key authentication."""
    provider = AzureOpenAIProvider(
        api_key="test-api-key-123",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )
    
    headers = provider._build_headers()
    assert headers["Content-Type"] == "application/json"
    assert headers["api-key"] == "test-api-key-123"  # Azure OpenAI specific header
    assert "x-session-affinity" in headers


def test_prepare_request_payload():
    """Test request payload preparation with Azure OpenAI 2024-10-21 compliance."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )
    
    messages = [{"role": "user", "content": "Hello"}]
    payload = provider._prepare_request_payload(messages, max_tokens=1500)
    
    assert payload["messages"] == messages
    assert payload["max_completion_tokens"] == 1500  # Azure API 2024-10-21 uses max_completion_tokens
    assert "temperature" not in payload  # Temperature not included in payload
    assert "tools" not in payload
    
    # Test with tools
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
    payload_with_tools = provider._prepare_request_payload(messages, tools=tools)
    assert payload_with_tools["tools"] == tools
    assert payload_with_tools["tool_choice"] == "auto"
    
    # Test with reasoning_effort
    payload_with_reasoning = provider._prepare_request_payload(messages, reasoning_effort="medium")
    assert payload_with_reasoning["reasoning_effort"] == "medium"


@pytest.mark.asyncio
async def test_chat_success():
    """Test successful chat request using model as deployment name."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o-deployment",
    )
    
    # Mock response data
    mock_response_data = {
        "choices": [{
            "message": {
                "content": "Hello! How can I help you today?",
                "role": "assistant"
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 18,
            "total_tokens": 30
        }
    }
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_response_data)
        
        mock_context = AsyncMock()
        mock_context.post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value = mock_context
        
        # Test with specific model (deployment name)
        messages = [{"role": "user", "content": "Hello"}]
        result = await provider.chat(messages, model="custom-deployment")
        
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello! How can I help you today?"
        assert result.finish_reason == "stop"
        assert result.usage["prompt_tokens"] == 12
        assert result.usage["completion_tokens"] == 18
        assert result.usage["total_tokens"] == 30
        
        # Verify URL was built with the provided model as deployment name
        call_args = mock_context.post.call_args
        expected_url = "https://test-resource.openai.azure.com/openai/deployments/custom-deployment/chat/completions?api-version=2024-10-21"
        assert call_args[0][0] == expected_url


@pytest.mark.asyncio
async def test_chat_uses_default_model_when_no_model_provided():
    """Test that chat uses default_model when no model is specified."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="default-deployment",
    )
    
    mock_response_data = {
        "choices": [{
            "message": {"content": "Response", "role": "assistant"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}
    }
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_response_data)
        
        mock_context = AsyncMock()
        mock_context.post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value = mock_context
        
        messages = [{"role": "user", "content": "Test"}]
        await provider.chat(messages)  # No model specified
        
        # Verify URL was built with default model as deployment name
        call_args = mock_context.post.call_args
        expected_url = "https://test-resource.openai.azure.com/openai/deployments/default-deployment/chat/completions?api-version=2024-10-21"
        assert call_args[0][0] == expected_url


@pytest.mark.asyncio
async def test_chat_with_tool_calls():
    """Test chat request with tool calls in response."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )
    
    # Mock response with tool calls
    mock_response_data = {
        "choices": [{
            "message": {
                "content": None,
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_12345",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"location": "San Francisco"}'
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 15,
            "total_tokens": 35
        }
    }
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_response_data)
        
        mock_context = AsyncMock()
        mock_context.post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value = mock_context
        
        messages = [{"role": "user", "content": "What's the weather?"}]
        tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
        result = await provider.chat(messages, tools=tools, model="weather-model")
        
        assert isinstance(result, LLMResponse)
        assert result.content is None
        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == {"location": "San Francisco"}


@pytest.mark.asyncio
async def test_chat_api_error():
    """Test chat request API error handling."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid authentication credentials"
        
        mock_context = AsyncMock()
        mock_context.post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value = mock_context
        
        messages = [{"role": "user", "content": "Hello"}]
        result = await provider.chat(messages)
        
        assert isinstance(result, LLMResponse)
        assert "Azure OpenAI API Error 401" in result.content
        assert "Invalid authentication credentials" in result.content
        assert result.finish_reason == "error"


@pytest.mark.asyncio
async def test_chat_connection_error():
    """Test chat request connection error handling."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )
    
    with patch("httpx.AsyncClient") as mock_client:
        mock_context = AsyncMock()
        mock_context.post = AsyncMock(side_effect=Exception("Connection failed"))
        mock_client.return_value.__aenter__.return_value = mock_context
        
        messages = [{"role": "user", "content": "Hello"}]
        result = await provider.chat(messages)
        
        assert isinstance(result, LLMResponse)
        assert "Error calling Azure OpenAI: Exception('Connection failed')" in result.content
        assert result.finish_reason == "error"


def test_parse_response_malformed():
    """Test response parsing with malformed data."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )
    
    # Test with missing choices
    malformed_response = {"usage": {"prompt_tokens": 10}}
    result = provider._parse_response(malformed_response)
    
    assert isinstance(result, LLMResponse)
    assert "Error parsing Azure OpenAI response" in result.content
    assert result.finish_reason == "error"


def test_get_default_model():
    """Test get_default_model method."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="my-custom-deployment",
    )
    
    assert provider.get_default_model() == "my-custom-deployment"


if __name__ == "__main__":
    # Run basic tests
    print("Running basic Azure OpenAI provider tests...")
    
    # Test initialization
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o-deployment",
    )
    print("✅ Provider initialization successful")
    
    # Test URL building
    url = provider._build_chat_url("my-deployment")
    expected = "https://test-resource.openai.azure.com/openai/deployments/my-deployment/chat/completions?api-version=2024-10-21"
    assert url == expected
    print("✅ URL building works correctly")
    
    # Test headers
    headers = provider._build_headers()
    assert headers["api-key"] == "test-key"
    assert headers["Content-Type"] == "application/json"
    print("✅ Header building works correctly")
    
    # Test payload preparation
    messages = [{"role": "user", "content": "Test"}]
    payload = provider._prepare_request_payload(messages, max_tokens=1000)
    assert payload["max_completion_tokens"] == 1000  # Azure 2024-10-21 format
    print("✅ Payload preparation works correctly")
    
    print("✅ All basic tests passed! Updated test file is working correctly.")