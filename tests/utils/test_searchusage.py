from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.command.results import render
from nanobot.command.status import search_lines, status_lines
from nanobot.providers.base import LLMUsage
from nanobot.utils.searchusage import (
    SearchUsageInfo,
    _parse_tavily_usage,
    fetch_search_usage,
)


def status_text(**kwargs):
    return render(tuple(status_lines(**kwargs)), "en")


class TestSearchUsageInfoFormat:
    def test_unsupported_provider_shows_no_tracking(self):
        info = SearchUsageInfo(provider="duckduckgo", supported=False)
        text = render(tuple(search_lines(info)), "en")
        assert "duckduckgo" in text
        assert "not available" in text

    def test_supported_with_error(self):
        info = SearchUsageInfo(provider="tavily", supported=True, error="HTTP 401")
        text = render(tuple(search_lines(info)), "en")
        assert "tavily" in text
        assert "HTTP 401" in text
        assert "unavailable" in text

    def test_usage_without_limit(self):
        info = SearchUsageInfo(provider="tavily", supported=True, used=50)
        text = render(tuple(search_lines(info)), "en")
        assert "50 requests" in text
        assert "/" not in text.split("Usage:")[1].split("\n")[0]

    def test_no_breakdown_when_none(self):
        info = SearchUsageInfo(
            provider="tavily", supported=True, used=10, limit=100, remaining=90
        )
        text = render(tuple(search_lines(info)), "en")
        assert "Breakdown" not in text

class TestParseTavilyUsage:
    def test_full_response(self):
        data = {
            "account": {
                "current_plan": "Researcher",
                "plan_usage": 142,
                "plan_limit": 1000,
                "search_usage": 120,
                "extract_usage": 15,
                "crawl_usage": 7,
                "map_usage": 0,
                "research_usage": 0,
                "paygo_usage": 0,
                "paygo_limit": None,
            },
        }
        info = _parse_tavily_usage(data)
        assert info.provider == "tavily"
        assert info.supported is True
        assert info.used == 142
        assert info.limit == 1000
        assert info.remaining == 858
        assert info.search_used == 120
        assert info.extract_used == 15
        assert info.crawl_used == 7

    def test_remaining_not_negative(self):
        data = {"account": {"plan_usage": 1100, "plan_limit": 1000}}
        info = _parse_tavily_usage(data)
        assert info.remaining == 0

    def test_empty_response(self):
        info = _parse_tavily_usage({})
        assert info.provider == "tavily"
        assert info.supported is True
        assert info.used is None
        assert info.limit is None

    def test_no_breakdown_fields(self):
        data = {"account": {"plan_usage": 5, "plan_limit": 50}}
        info = _parse_tavily_usage(data)
        assert info.search_used is None
        assert info.extract_used is None
        assert info.crawl_used is None

    def test_string_numeric_fields(self):
        data = {
            "account": {
                "plan_usage": "10",
                "plan_limit": "100",
                "search_usage": "7",
                "extract_usage": "2",
                "crawl_usage": "1",
            },
        }
        info = _parse_tavily_usage(data)
        assert info.used == 10
        assert info.limit == 100
        assert info.remaining == 90
        assert info.search_used == 7
        assert info.extract_used == 2
        assert info.crawl_used == 1


class TestFetchSearchUsageRouting:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ["duckduckgo", "searxng", "jina", "brave", "some_unknown_provider"])
    async def test_provider_returns_unsupported(self, provider):
        info = await fetch_search_usage(provider)
        assert info.provider == provider
        assert info.supported is False

    @pytest.mark.asyncio
    async def test_tavily_no_api_key_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("TAVILY_API_KEY", None)
            info = await fetch_search_usage("tavily", api_key=None)
        assert info.provider == "tavily"
        assert info.supported is True
        assert info.error is not None
        assert "not configured" in info.error

    @pytest.mark.asyncio
    async def test_tavily_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "account": {
                "current_plan": "Researcher",
                "plan_usage": 142,
                "plan_limit": 1000,
                "search_usage": 120,
                "extract_usage": 15,
                "crawl_usage": 7,
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            info = await fetch_search_usage("tavily", api_key="test-key")

        assert info.provider == "tavily"
        assert info.supported is True
        assert info.error is None
        assert info.used == 142
        assert info.limit == 1000
        assert info.remaining == 858
        assert info.search_used == 120

    @pytest.mark.asyncio
    async def test_tavily_http_error(self):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            info = await fetch_search_usage("tavily", api_key="bad-key")

        assert info.supported is True
        assert info.error == "HTTP 401"

    @pytest.mark.asyncio
    async def test_tavily_network_error(self):
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            info = await fetch_search_usage("tavily", api_key="test-key")

        assert info.supported is True
        assert info.error is not None

    @pytest.mark.asyncio
    async def test_provider_name_case_insensitive(self):
        info = await fetch_search_usage("Tavily", api_key=None)
        assert info.provider == "tavily"
        assert info.supported is True


class TestBuildStatusContentWithSearchUsage:
    _BASE_KWARGS = dict(
        version="0.1.0",
        model="claude-opus-4-5",
        start_time=1_000_000.0,
        last_usage=LLMUsage.reported(input_tokens=1000, output_tokens=200),
        context_window_tokens=65536,
        session_msg_count=5,
        context_tokens=3000,
    )

    def test_no_search_usage_unchanged(self):
        content = status_text(**self._BASE_KWARGS)
        assert "🔍" not in content
        assert "Web Search" not in content

    def test_existing_fields_still_present(self):
        usage = SearchUsageInfo(provider="duckduckgo")
        content = status_text(**self._BASE_KWARGS, search_usage=usage)
        assert "nanobot v0.1.0" in content
        assert "claude-opus-4-5" in content
        assert "1000 in / 200 out" in content
        assert "duckduckgo" in content

    def test_full_tavily_in_status(self):
        info = SearchUsageInfo(
            provider="tavily",
            supported=True,
            used=142,
            limit=1000,
            remaining=858,
            reset_date="2026-05-01",
            search_used=120,
            extract_used=15,
            crawl_used=7,
        )
        content = status_text(**self._BASE_KWARGS, search_usage=info)
        assert "142 / 1000" in content
        assert "858" in content
        assert "2026-05-01" in content
        assert "🔍 Web Search: tavily" in content
        assert "Search: 120" in content
        assert "Extract: 15" in content
        assert "Crawl: 7" in content
