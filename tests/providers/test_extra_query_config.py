"""Tests for provider extra_query config injection into client defaults."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nanobot.config.schema import Config, ProviderConfig
from nanobot.providers.factory import provider_signature
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


class TestExtraQuerySchema:
    """Verify ProviderConfig accepts extra_query."""

    def test_default_is_none(self) -> None:
        config = ProviderConfig()
        assert config.extra_query is None

    def test_accepts_dict(self) -> None:
        config = ProviderConfig(extra_query={"api-version": "2024-02-01"})
        assert config.extra_query == {"api-version": "2024-02-01"}


class TestExtraQueryInit:
    """Verify the provider stores extra_query from config."""

    def test_default_is_empty(self) -> None:
        provider = OpenAICompatProvider(api_key="test")
        assert provider._extra_query == {}

    def test_none_becomes_empty(self) -> None:
        provider = OpenAICompatProvider(api_key="test", extra_query=None)
        assert provider._extra_query == {}

    def test_dict_stored(self) -> None:
        query = {"api-version": "v1"}
        provider = OpenAICompatProvider(api_key="test", extra_query=query)
        assert provider._extra_query == query


class TestExtraQueryBuildClient:
    """Verify extra_query flows into AsyncOpenAI default_query."""

    def test_build_client_passes_default_query(self) -> None:
        mock_client = MagicMock()
        with patch(
            "nanobot.providers.openai_compat_provider.AsyncOpenAI",
            return_value=mock_client,
        ) as mock_async_openai:
            provider = OpenAICompatProvider(
                api_key="test",
                extra_query={"api-version": "v1"},
            )
            provider._build_client()

        assert provider._client is mock_client
        assert mock_async_openai.call_args.kwargs["default_query"] == {"api-version": "v1"}

    def test_build_client_passes_no_default_query_when_empty(self) -> None:
        mock_client = MagicMock()
        with patch(
            "nanobot.providers.openai_compat_provider.AsyncOpenAI",
            return_value=mock_client,
        ) as mock_async_openai:
            provider = OpenAICompatProvider(api_key="test")
            provider._build_client()

        assert provider._client is mock_client
        kwargs = mock_async_openai.call_args.kwargs
        assert "default_query" not in kwargs or kwargs["default_query"] is None


class TestProviderSignatureIncludesExtraQuery:
    """Verify provider_signature tracks provider extra_query changes."""

    def test_provider_signature_tracks_extra_query(self) -> None:
        base = {
            "agents": {"defaults": {"modelPreset": "fast"}},
            "modelPresets": {
                "fast": {"model": "custom/test-model", "provider": "custom"},
            },
            "providers": {
                "custom": {
                    "apiKey": "test-key",
                    "extra_query": None,
                },
            },
        }
        changed_query = {
            **base,
            "providers": {
                "custom": {
                    "apiKey": "test-key",
                    "extra_query": {"api-version": "v1"},
                },
            },
        }

        signature = provider_signature(Config.model_validate(base))

        assert signature != provider_signature(Config.model_validate(changed_query))
