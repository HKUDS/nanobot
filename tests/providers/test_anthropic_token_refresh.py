"""Tests for AnthropicProvider._ensure_valid_token integration."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.oauth_store import OAuthCredentials, OAuthCredentialStore


def _make_store(access_token, refresh_token, expires_at_ms):
    store = MagicMock(spec=OAuthCredentialStore)
    store.load.return_value = OAuthCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_ms=expires_at_ms,
    )
    store.save = MagicMock()
    return store


def _make_mock_client():
    mock_messages = MagicMock()
    mock_response = MagicMock()
    mock_response.content = []
    mock_response.stop_reason = "end_turn"
    mock_response.usage = None
    mock_messages.create = AsyncMock(return_value=mock_response)
    mock_client = MagicMock()
    mock_client.messages = mock_messages
    return mock_client


@pytest.mark.asyncio
async def test_no_refresh_when_token_valid():
    future_expiry = int(time.time() * 1000) + 3_600_000
    store = _make_store("sk-ant-oat01-valid", "sk-ant-ort01-r", future_expiry)

    with patch("nanobot.providers.anthropic_provider.refresh_anthropic_token") as mock_refresh:
        provider = AnthropicProvider(
            api_key="sk-ant-oat01-valid",
            credential_store=store,
        )
        provider._token_expires_at_ms = future_expiry
        provider._client = _make_mock_client()

        await provider.chat([{"role": "user", "content": "hi"}])
        mock_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_triggered_when_token_expired():
    expired = int(time.time() * 1000) - 1000
    store = _make_store("sk-ant-oat01-old", "sk-ant-ort01-r", expired)

    new_creds = OAuthCredentials(
        access_token="sk-ant-oat01-new",
        refresh_token="sk-ant-ort01-new-r",
        expires_at_ms=int(time.time() * 1000) + 3_600_000,
    )

    with patch("nanobot.providers.anthropic_provider.refresh_anthropic_token",
               new=AsyncMock(return_value=new_creds)) as mock_refresh:
        provider = AnthropicProvider(
            api_key="sk-ant-oat01-old",
            credential_store=store,
        )
        provider._token_expires_at_ms = expired
        provider._client = _make_mock_client()
        provider._update_oauth_client = MagicMock()

        await provider.chat([{"role": "user", "content": "hi"}])

        mock_refresh.assert_called_once_with("sk-ant-ort01-r")
        store.save.assert_called_once_with(new_creds)
        provider._update_oauth_client.assert_called_once_with("sk-ant-oat01-new")


@pytest.mark.asyncio
async def test_concurrent_refresh_only_runs_once():
    expired = int(time.time() * 1000) - 1000
    store = _make_store("sk-ant-oat01-old", "sk-ant-ort01-r", expired)

    refresh_call_count = 0

    async def mock_refresh(rt):
        nonlocal refresh_call_count
        refresh_call_count += 1
        await asyncio.sleep(0.01)
        return OAuthCredentials(
            access_token="sk-ant-oat01-new",
            refresh_token="sk-ant-ort01-new-r",
            expires_at_ms=int(time.time() * 1000) + 3_600_000,
        )

    with patch("nanobot.providers.anthropic_provider.refresh_anthropic_token", side_effect=mock_refresh):
        provider = AnthropicProvider(
            api_key="sk-ant-oat01-old",
            credential_store=store,
        )
        provider._token_expires_at_ms = expired
        provider._client = _make_mock_client()
        provider._update_oauth_client = MagicMock()

        await asyncio.gather(
            provider.chat([{"role": "user", "content": "hi"}]),
            provider.chat([{"role": "user", "content": "hello"}]),
        )

        assert refresh_call_count == 1
