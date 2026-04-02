"""Tests for auto context window detection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.cli.models import _normalize_model_name, get_model_context_limit
from nanobot.providers.context_window import (
    _HARD_DEFAULT,
    resolve_context_window,
    resolve_context_window_sync,
)


# ---------------------------------------------------------------------------
# _normalize_model_name
# ---------------------------------------------------------------------------

class TestNormalizeModelName:
    def test_with_provider_prefix(self):
        assert _normalize_model_name("anthropic/claude-sonnet-4-6") == "claude-sonnet-4-6"

    def test_with_nested_prefix(self):
        # rsplit("/", 1) takes last segment
        assert _normalize_model_name("openrouter/anthropic/claude-sonnet-4-6") == "claude-sonnet-4-6"

    def test_with_date_suffix(self):
        assert _normalize_model_name("claude-sonnet-4-6-20260301") == "claude-sonnet-4-6"

    def test_with_prefix_and_date(self):
        assert _normalize_model_name("anthropic/claude-3-opus-20240229") == "claude-3-opus"

    def test_plain(self):
        assert _normalize_model_name("gpt-4o") == "gpt-4o"

    def test_uppercase(self):
        assert _normalize_model_name("Claude-Sonnet-4-6") == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# get_model_context_limit
# ---------------------------------------------------------------------------

class TestGetModelContextLimit:
    def test_exact_match(self):
        assert get_model_context_limit("claude-sonnet-4-6") == 1_000_000

    def test_with_prefix(self):
        assert get_model_context_limit("anthropic/claude-sonnet-4-6") == 1_000_000

    def test_with_date_suffix(self):
        assert get_model_context_limit("claude-3-opus-20240229") == 200_000

    def test_prefix_match_longest_wins_gpt4o_mini(self):
        # "gpt-4o-mini" should match "gpt-4o-mini" (128k), not "gpt-4o" or "gpt-4"
        assert get_model_context_limit("gpt-4o-mini") == 128_000

    def test_prefix_match_longest_wins_gpt4o(self):
        # "gpt-4o" should match "gpt-4o" (128k), not "gpt-4" (8k)
        assert get_model_context_limit("gpt-4o") == 128_000

    def test_prefix_match_longest_wins_o1_mini(self):
        # "o1-mini" should match "o1-mini" (128k), not "o1" (200k)
        assert get_model_context_limit("o1-mini") == 128_000

    def test_prefix_match_longest_wins_o3_mini(self):
        assert get_model_context_limit("o3-mini") == 200_000

    def test_gpt4_plain(self):
        assert get_model_context_limit("gpt-4") == 8_192

    def test_claude_4_6_opus(self):
        assert get_model_context_limit("claude-opus-4-6") == 1_000_000

    def test_unknown_model(self):
        assert get_model_context_limit("some-random-model-xyz") is None

    def test_deepseek(self):
        assert get_model_context_limit("deepseek-chat") == 65_536

    def test_gemini(self):
        assert get_model_context_limit("gemini-2.5-pro") == 1_000_000

    def test_llama(self):
        assert get_model_context_limit("llama-3.1-70b") == 131_072

    def test_full_openrouter_path(self):
        assert get_model_context_limit("openrouter/anthropic/claude-sonnet-4-6") == 1_000_000


# ---------------------------------------------------------------------------
# resolve_context_window (async)
# ---------------------------------------------------------------------------

class TestResolveContextWindow:
    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def _mock_provider(self, api_return=None):
        provider = AsyncMock()
        provider.fetch_model_context_window = AsyncMock(return_value=api_return)
        return provider

    def test_api_wins(self):
        provider = self._mock_provider(api_return=500_000)
        tokens, source = self._run(
            resolve_context_window(provider, "some-model", 0)
        )
        assert tokens == 500_000
        assert source == "api"

    def test_api_fails_falls_to_lookup(self):
        provider = self._mock_provider(api_return=None)
        tokens, source = self._run(
            resolve_context_window(provider, "claude-sonnet-4-6", 0)
        )
        assert tokens == 1_000_000
        assert source == "lookup"

    def test_api_and_lookup_fail_falls_to_config(self):
        provider = self._mock_provider(api_return=None)
        tokens, source = self._run(
            resolve_context_window(provider, "unknown-model-xyz", 300_000)
        )
        assert tokens == 300_000
        assert source == "config"

    def test_all_fail_returns_default(self):
        provider = self._mock_provider(api_return=None)
        tokens, source = self._run(
            resolve_context_window(provider, "unknown-model-xyz", 0)
        )
        assert tokens == _HARD_DEFAULT
        assert source == "default"

    def test_api_returns_zero_ignored(self):
        provider = self._mock_provider(api_return=0)
        tokens, source = self._run(
            resolve_context_window(provider, "claude-sonnet-4-6", 0)
        )
        # API returned 0 → ignored → falls to lookup
        assert tokens == 1_000_000
        assert source == "lookup"

    def test_api_exception_falls_through(self):
        provider = AsyncMock()
        provider.fetch_model_context_window = AsyncMock(side_effect=RuntimeError("boom"))
        tokens, source = self._run(
            resolve_context_window(provider, "claude-sonnet-4-6", 0)
        )
        assert tokens == 1_000_000
        assert source == "lookup"


# ---------------------------------------------------------------------------
# resolve_context_window_sync
# ---------------------------------------------------------------------------

class TestResolveContextWindowSync:
    def test_lookup_hit(self):
        tokens, source = resolve_context_window_sync("claude-sonnet-4-6", 0)
        assert tokens == 1_000_000
        assert source == "lookup"

    def test_config_fallback(self):
        tokens, source = resolve_context_window_sync("unknown-model", 200_000)
        assert tokens == 200_000
        assert source == "config"

    def test_default(self):
        tokens, source = resolve_context_window_sync("unknown-model", 0)
        assert tokens == _HARD_DEFAULT
        assert source == "default"
