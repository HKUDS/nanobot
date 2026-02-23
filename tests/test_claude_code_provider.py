import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nanobot.providers.claude_code_provider import ClaudeCodeProvider


@pytest.mark.asyncio
async def test_401_returns_error_with_setup_token_hint():
    """On 401, provider should return error message suggesting claude setup-token."""
    provider = ClaudeCodeProvider(oauth_token="sk-ant-oat01-expired")

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with patch.object(provider, "_send_request", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.finish_reason == "error"
    assert "setup-token" in result.content.lower()


@pytest.mark.asyncio
async def test_no_refresh_token_method():
    """_refresh_token should no longer exist."""
    provider = ClaudeCodeProvider(oauth_token="sk-ant-oat01-test")
    assert not hasattr(provider, "_refresh_token")
