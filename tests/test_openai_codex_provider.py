from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.openai_codex_provider import OpenAICodexProvider


@pytest.mark.asyncio
async def test_openai_codex_provider_uses_configured_proxy_without_oauth() -> None:
    provider = OpenAICodexProvider(
        default_model="openai-codex/gpt-5.4",
        api_base="https://proxy.example/v1/responses",
        api_key="proxy-key",
        extra_headers={"X-Test": "demo"},
    )

    with patch(
        "nanobot.providers.openai_codex_provider._request_codex",
        new=AsyncMock(return_value=("ok", [], "stop")),
    ) as mock_request, patch(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        side_effect=AssertionError("OAuth should not be used when api_key is configured"),
    ):
        result = await provider.chat([{"role": "user", "content": "hello"}])

    assert result.content == "ok"
    assert result.finish_reason == "stop"

    called_url, headers, body = mock_request.await_args.args[:3]
    assert called_url == "https://proxy.example/v1/responses"
    assert headers["Authorization"] == "Bearer proxy-key"
    assert headers["X-Test"] == "demo"
    assert "chatgpt-account-id" not in headers
    assert body["model"] == "gpt-5.4"
