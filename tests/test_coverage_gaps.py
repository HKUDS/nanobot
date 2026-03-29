"""Tests to close coverage gaps in pure-logic modules.

Targets modules with uncovered lines that require no external dependencies:
errors, bus/events, strategy_extractor (_infer_domain, _llm_summarize fallback),
providers/__init__.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# errors.py — ProviderError, BudgetExceededError (lines 103-119)
# ---------------------------------------------------------------------------


class TestProviderError:
    def test_provider_error_attributes(self) -> None:
        from nanobot.errors import ProviderError

        err = ProviderError("openai", "rate limit", status_code=429, retryable=True)
        assert err.provider == "openai"
        assert err.status_code == 429
        assert err.retryable is True
        assert "rate limit" in str(err)

    def test_provider_error_defaults(self) -> None:
        from nanobot.errors import ProviderError

        err = ProviderError("litellm", "timeout")
        assert err.status_code is None
        assert err.retryable is True

    def test_budget_exceeded_error(self) -> None:
        from nanobot.errors import BudgetExceededError

        err = BudgetExceededError(spent_usd=1.5, budget_usd=1.0)
        assert err.spent_usd == 1.5
        assert err.budget_usd == 1.0
        assert err.retryable is False
        assert "1.5000" in str(err)
        assert "1.0000" in str(err)


# ---------------------------------------------------------------------------
# bus/events.py — ReactionEvent.rating (lines 115-120)
# ---------------------------------------------------------------------------


class TestReactionEventRating:
    def test_positive_thumbsup(self) -> None:
        from nanobot.bus.events import ReactionEvent

        r = ReactionEvent(channel="test", sender_id="u1", chat_id="c1", emoji="\U0001f44d")
        assert r.rating == "positive"

    def test_positive_plus_one(self) -> None:
        from nanobot.bus.events import ReactionEvent

        r = ReactionEvent(channel="test", sender_id="u1", chat_id="c1", emoji="+1")
        assert r.rating == "positive"

    def test_negative_thumbsdown(self) -> None:
        from nanobot.bus.events import ReactionEvent

        r = ReactionEvent(channel="test", sender_id="u1", chat_id="c1", emoji="\U0001f44e")
        assert r.rating == "negative"

    def test_negative_angry(self) -> None:
        from nanobot.bus.events import ReactionEvent

        r = ReactionEvent(channel="test", sender_id="u1", chat_id="c1", emoji="angry")
        assert r.rating == "negative"

    def test_ambiguous_returns_none(self) -> None:
        from nanobot.bus.events import ReactionEvent

        r = ReactionEvent(channel="test", sender_id="u1", chat_id="c1", emoji="\U0001f914")
        assert r.rating is None


# ---------------------------------------------------------------------------
# strategy_extractor.py — _infer_domain branches, _llm_summarize (lines 142-172)
# ---------------------------------------------------------------------------


class TestStrategyExtractorHelpers:
    def test_infer_domain_obsidian(self) -> None:
        from nanobot.memory.strategy_extractor import StrategyExtractor

        assert StrategyExtractor._infer_domain("obsidian_search", "list_dir") == "obsidian"

    def test_infer_domain_github(self) -> None:
        from nanobot.memory.strategy_extractor import StrategyExtractor

        assert StrategyExtractor._infer_domain("git_log", "read_file") == "github"
        assert StrategyExtractor._infer_domain("exec", "github_search") == "github"

    def test_infer_domain_web(self) -> None:
        from nanobot.memory.strategy_extractor import StrategyExtractor

        assert StrategyExtractor._infer_domain("web_fetch", "read_file") == "web"

    def test_infer_domain_filesystem_default(self) -> None:
        from nanobot.memory.strategy_extractor import StrategyExtractor

        assert StrategyExtractor._infer_domain("exec", "read_file") == "filesystem"

    @pytest.mark.asyncio
    async def test_llm_summarize_success(self) -> None:
        from nanobot.memory.strategy import StrategyAccess
        from nanobot.memory.strategy_extractor import StrategyExtractor
        from nanobot.memory.unified_db import STRATEGIES_DDL

        mock_provider = AsyncMock()
        mock_response = AsyncMock()
        mock_response.content = "Use list_dir instead of obsidian search for folder names."
        mock_provider.chat = AsyncMock(return_value=mock_response)

        conn = sqlite3.connect(":memory:")
        conn.executescript(STRATEGIES_DDL)
        store = StrategyAccess(conn)
        extractor = StrategyExtractor(store=store, provider=mock_provider, model="test")

        result = await extractor._llm_summarize(
            "find DS10540", "obsidian_search", '{"query": "DS10540"}', "list_dir", '{"path": "/"}'
        )
        assert result == "Use list_dir instead of obsidian search for folder names."
        mock_provider.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_summarize_fallback_on_error(self) -> None:
        from nanobot.memory.strategy import StrategyAccess
        from nanobot.memory.strategy_extractor import StrategyExtractor
        from nanobot.memory.unified_db import STRATEGIES_DDL

        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(side_effect=RuntimeError("API down"))

        conn = sqlite3.connect(":memory:")
        conn.executescript(STRATEGIES_DDL)
        store = StrategyAccess(conn)
        extractor = StrategyExtractor(store=store, provider=mock_provider, model="test")

        result = await extractor._llm_summarize(
            "find notes", "obsidian_search", "{}", "list_dir", "{}"
        )
        assert "list_dir" in result
        assert "obsidian_search" in result

    @pytest.mark.asyncio
    async def test_llm_summarize_empty_content_fallback(self) -> None:
        from nanobot.memory.strategy import StrategyAccess
        from nanobot.memory.strategy_extractor import StrategyExtractor
        from nanobot.memory.unified_db import STRATEGIES_DDL

        mock_provider = AsyncMock()
        mock_response = AsyncMock()
        mock_response.content = ""  # empty response
        mock_provider.chat = AsyncMock(return_value=mock_response)

        conn = sqlite3.connect(":memory:")
        conn.executescript(STRATEGIES_DDL)
        store = StrategyAccess(conn)
        extractor = StrategyExtractor(store=store, provider=mock_provider, model="")

        result = await extractor._llm_summarize("test", "exec", "{}", "read_file", "{}")
        # Empty content triggers the `or` fallback
        assert "read_file" in result


# ---------------------------------------------------------------------------
# providers/__init__.py — OpenAICodexProvider import (lines 14-16)
# ---------------------------------------------------------------------------


class TestProvidersInit:
    def test_exports_core_providers(self) -> None:
        from nanobot import providers

        assert hasattr(providers, "LLMProvider")
        assert hasattr(providers, "LiteLLMProvider")
        assert "LLMProvider" in providers.__all__


# ---------------------------------------------------------------------------
# config/loader.py — _migrate_graph_enabled, load_config (lines 20-22, 33-34, 60)
# ---------------------------------------------------------------------------


class TestConfigLoader:
    def test_migrate_graph_enabled(self) -> None:
        from nanobot.config.loader import _migrate_graph_enabled

        data: dict = {"agents": {"defaults": {"graph_enabled": True}}}
        _migrate_graph_enabled(data)
        assert "graph_enabled" not in data["agents"]["defaults"]
        assert data["agents"]["defaults"]["memory"]["graph_enabled"] is True

    def test_migrate_graph_enabled_noop_when_absent(self) -> None:
        from nanobot.config.loader import _migrate_graph_enabled

        data: dict = {"agents": {"defaults": {"model": "gpt-4o"}}}
        _migrate_graph_enabled(data)
        assert "memory" not in data["agents"]["defaults"]

    def test_load_config_default_when_no_file(self, tmp_path) -> None:
        from nanobot.config.loader import load_config

        config = load_config(tmp_path / "nonexistent.json")
        assert config is not None

    def test_get_data_dir(self) -> None:
        from nanobot.config.loader import get_data_dir

        d = get_data_dir()
        assert d is not None


# ---------------------------------------------------------------------------
# strategy_extractor.py — extract_from_turn with LLM provider (line 98)
# ---------------------------------------------------------------------------


class TestStrategyExtractorWithLLM:
    @pytest.mark.asyncio
    async def test_extract_with_llm_provider(self) -> None:
        from nanobot.agent.turn_types import ToolAttempt
        from nanobot.memory.strategy import StrategyAccess
        from nanobot.memory.strategy_extractor import StrategyExtractor
        from nanobot.memory.unified_db import STRATEGIES_DDL

        mock_provider = AsyncMock()
        mock_response = AsyncMock()
        mock_response.content = "For folder lookups, use list_dir instead of search."
        mock_provider.chat = AsyncMock(return_value=mock_response)

        conn = sqlite3.connect(":memory:")
        conn.executescript(STRATEGIES_DDL)
        store = StrategyAccess(conn)
        extractor = StrategyExtractor(store=store, provider=mock_provider, model="test")

        tool_log = [
            ToolAttempt(
                tool_name="obsidian_search",
                arguments={"query": "DS10540"},
                success=True,
                output_empty=True,
                output_snippet="",
                iteration=1,
            ),
            ToolAttempt(
                tool_name="list_dir",
                arguments={"path": "/vault"},
                success=True,
                output_empty=False,
                output_snippet="DS10540/",
                iteration=3,
            ),
        ]
        activations = [
            {
                "source": "empty_result_recovery",
                "severity": "directive",
                "iteration": 2,
                "message": "Try different approach",
                "strategy_tag": "empty_recovery:obsidian",
                "failed_tool": "obsidian_search",
                "failed_args": '{"query": "DS10540"}',
            }
        ]

        strategies = await extractor.extract_from_turn(
            tool_results_log=tool_log,
            guardrail_activations=activations,
            user_text="Find DS10540 project notes",
        )
        assert len(strategies) == 1
        assert strategies[0].strategy == "For folder lookups, use list_dir instead of search."
        mock_provider.chat.assert_called_once()
