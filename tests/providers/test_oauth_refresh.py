"""Tests for refresh_anthropic_token()."""
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.providers.oauth_store import refresh_anthropic_token


MOCK_RESPONSE = {
    "access_token": "sk-ant-oat01-new-access",
    "refresh_token": "sk-ant-ort01-new-refresh",
    "expires_in": 28800,
}


@pytest.mark.asyncio
async def test_refresh_returns_new_credentials():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = json.dumps(MOCK_RESPONSE)
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=MOCK_RESPONSE)

    with patch("nanobot.providers.oauth_store.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await refresh_anthropic_token("sk-ant-ort01-old-refresh")

    assert result.access_token == "sk-ant-oat01-new-access"
    assert result.refresh_token == "sk-ant-ort01-new-refresh"
    assert result.expires_at_ms > int(time.time() * 1000)


@pytest.mark.asyncio
async def test_refresh_raises_on_http_error():
    import httpx
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = '{"error": "invalid_grant"}'
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=mock_response)
    )

    with patch("nanobot.providers.oauth_store.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="token refresh"):
            await refresh_anthropic_token("bad-token")


@pytest.mark.asyncio
async def test_refresh_posts_correct_payload():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = json.dumps(MOCK_RESPONSE)
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=MOCK_RESPONSE)

    with patch("nanobot.providers.oauth_store.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await refresh_anthropic_token("sk-ant-ort01-test")

        call_args = mock_client.post.call_args
        sent_json = call_args.kwargs.get("json") or call_args[1].get("json")
        assert sent_json["grant_type"] == "refresh_token"
        assert sent_json["client_id"] == "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
        assert sent_json["refresh_token"] == "sk-ant-ort01-test"
