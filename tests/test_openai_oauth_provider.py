from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from oauth_cli_kit import OAuthToken

from nanobot.providers.openai_oauth_provider import OpenAIOAuthProvider, _strip_model_prefix


def test_strip_model_prefix_supports_hyphen_and_underscore():
    assert _strip_model_prefix("openai-oauth/gpt-5.1") == "gpt-5.1"
    assert _strip_model_prefix("openai_oauth/gpt-5.1") == "gpt-5.1"


@pytest.mark.asyncio
async def test_openai_oauth_provider_uses_oauth_token_for_responses_api(monkeypatch):
    fake_response = SimpleNamespace(
        model_dump=lambda mode="json": {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "hello from oauth"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "id": "fc_1",
                    "name": "weather",
                    "arguments": "{\"city\": \"Shanghai\"}",
                },
            ],
            "usage": {
                "input_tokens": 12,
                "output_tokens": 7,
                "total_tokens": 19,
            },
        }
    )

    configured_client = MagicMock()
    configured_client.responses.create = AsyncMock(return_value=fake_response)
    base_client = MagicMock()
    base_client.with_options.return_value = configured_client

    monkeypatch.setattr(
        "nanobot.providers.openai_oauth_provider.get_token",
        lambda provider=None: OAuthToken(
            access="access-token",
            refresh="refresh-token",
            expires=9999999999999,
            account_id="acct_123",
        ),
    )

    with patch("nanobot.providers.openai_oauth_provider.AsyncOpenAI", return_value=base_client):
        provider = OpenAIOAuthProvider(default_model="openai-oauth/gpt-5.1")

    response = await provider.chat(
        messages=[
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "What's the weather?"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "Get weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                },
            }
        ],
        reasoning_effort="medium",
        max_tokens=256,
    )

    base_client.with_options.assert_called_once_with(api_key="access-token")
    configured_client.responses.create.assert_awaited_once()
    _, kwargs = configured_client.responses.create.await_args
    assert kwargs["model"] == "gpt-5.1"
    assert kwargs["instructions"] == "Be concise."
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["tool_choice"] == "auto"
    assert kwargs["parallel_tool_calls"] is True
    assert kwargs["extra_headers"] == {"chatgpt-account-id": "acct_123"}
    assert response.content == "hello from oauth"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].name == "weather"
    assert response.tool_calls[0].arguments == {"city": "Shanghai"}

