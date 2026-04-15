"""Tests for Anthropic native token counting via estimate_prompt_tokens."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def _patch_anthropic():
    """Patch both Anthropic clients so no real SDK import is needed."""
    with (
        patch("anthropic.AsyncAnthropic") as mock_async,
        patch("anthropic.Anthropic") as mock_sync,
    ):
        yield mock_async, mock_sync


class TestEstimatePromptTokens:
    """AnthropicProvider.estimate_prompt_tokens() behaviour."""

    @staticmethod
    def _make_provider(**kwargs):
        from nanobot.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key="test-key", **kwargs)

    def test_returns_count(self, _patch_anthropic):
        provider = self._make_provider()
        mock_result = MagicMock()
        mock_result.input_tokens = 150
        provider._sync_client.messages.count_tokens.return_value = mock_result

        result = provider.estimate_prompt_tokens(
            [{"role": "user", "content": "hello"}],
            None,
            "claude-sonnet-4-20250514",
        )

        assert result == (150, "anthropic_count_tokens")
        provider._sync_client.messages.count_tokens.assert_called_once()

    def test_returns_none_on_error(self, _patch_anthropic):
        provider = self._make_provider()
        provider._sync_client.messages.count_tokens.side_effect = Exception("fail")

        result = provider.estimate_prompt_tokens(
            [{"role": "user", "content": "hello"}],
            None,
        )

        assert result is None

    def test_sync_client_created(self, _patch_anthropic):
        _, mock_sync = _patch_anthropic
        provider = self._make_provider()

        assert provider._sync_client is not None
        mock_sync.assert_called_once()

    def test_passes_tools_when_provided(self, _patch_anthropic):
        provider = self._make_provider()
        mock_result = MagicMock()
        mock_result.input_tokens = 200
        provider._sync_client.messages.count_tokens.return_value = mock_result

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = provider.estimate_prompt_tokens(
            [{"role": "user", "content": "weather?"}],
            tools,
            "claude-sonnet-4-20250514",
        )

        assert result == (200, "anthropic_count_tokens")
        call_kwargs = provider._sync_client.messages.count_tokens.call_args
        assert "tools" in call_kwargs.kwargs or (
            len(call_kwargs.args) > 0 and "tools" in call_kwargs[1]
        )

    def test_passes_system_when_present(self, _patch_anthropic):
        provider = self._make_provider()
        mock_result = MagicMock()
        mock_result.input_tokens = 100
        provider._sync_client.messages.count_tokens.return_value = mock_result

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
        provider.estimate_prompt_tokens(messages, None)

        call_kwargs = provider._sync_client.messages.count_tokens.call_args.kwargs
        assert "system" in call_kwargs

    def test_strips_anthropic_prefix_from_model(self, _patch_anthropic):
        provider = self._make_provider()
        mock_result = MagicMock()
        mock_result.input_tokens = 50
        provider._sync_client.messages.count_tokens.return_value = mock_result

        provider.estimate_prompt_tokens(
            [{"role": "user", "content": "hi"}],
            None,
            "anthropic/claude-sonnet-4-20250514",
        )

        call_kwargs = provider._sync_client.messages.count_tokens.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"

    def test_uses_default_model_when_none(self, _patch_anthropic):
        provider = self._make_provider(default_model="claude-haiku-4-20250514")
        mock_result = MagicMock()
        mock_result.input_tokens = 30
        provider._sync_client.messages.count_tokens.return_value = mock_result

        provider.estimate_prompt_tokens(
            [{"role": "user", "content": "hi"}],
            None,
        )

        call_kwargs = provider._sync_client.messages.count_tokens.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-20250514"
