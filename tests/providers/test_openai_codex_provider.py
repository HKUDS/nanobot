from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.openai_codex_provider import OpenAICodexProvider


@pytest.mark.asyncio
async def test_openai_codex_native_web_search_adds_responses_tool():
    request_mock = AsyncMock(return_value=("latest AI news", [], "stop"))

    with patch("nanobot.providers.openai_codex_provider.get_codex_token") as mock_token, \
         patch("nanobot.providers.openai_codex_provider._request_codex", request_mock):
        mock_token.return_value = SimpleNamespace(account_id="acct_123", access="token_123")
        provider = OpenAICodexProvider(
            default_model="openai-codex/gpt-5.1-codex",
            native_web_search_tool={
                "type": "web_search",
                "user_location": {"type": "approximate", "country": "US"},
            },
        )

        result = await provider.chat(
            messages=[{"role": "user", "content": "latest AI news"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "exec",
                        "description": "Run shell commands",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

    body = request_mock.call_args.args[2]
    assert body["tools"][0]["type"] == "function"
    assert body["tools"][0]["name"] == "exec"
    assert body["tools"][1] == {
        "type": "web_search",
        "user_location": {"type": "approximate", "country": "US"},
    }
    assert result.content == "latest AI news"


@pytest.mark.asyncio
async def test_openai_codex_native_web_search_without_other_tools_still_sets_tools():
    request_mock = AsyncMock(return_value=("ok", [], "stop"))

    with patch("nanobot.providers.openai_codex_provider.get_codex_token") as mock_token, \
         patch("nanobot.providers.openai_codex_provider._request_codex", request_mock):
        mock_token.return_value = SimpleNamespace(account_id="acct_123", access="token_123")
        provider = OpenAICodexProvider(
            native_web_search_tool={"type": "web_search"},
        )

        await provider.chat(messages=[{"role": "user", "content": "search this"}])

    body = request_mock.call_args.args[2]
    assert body["tools"] == [{"type": "web_search"}]
    assert provider.uses_native_web_search() is True
