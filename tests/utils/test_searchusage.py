"""Tests for web search provider usage fetching and /status integration."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.utils.searchusage import (
    SearchUsageInfo,
    _parse_tavily_usage,
    fetch_search_usage,
)
from nanobot.utils.helpers import build_status_content


# ---------------------------------------------------------------------------
# SearchUsageInfo.format() tests
# ---------------------------------------------------------------------------

class TestSearchUsageInfoFormat:
    def test_unsupported_provider_shows_no_tracking(self):
        info = SearchUsageInfo(provider="duckduckgo", supported=False)
        text = info.format()
        assert "duckduckgo" in text
        assert "not available" in text

    def test_supported_with_error(self):
        info = SearchUsageInfo(provider="tavily", supported=True, error="HTTP 401")
        text = info.format()
        assert "tavily" in text
        assert "HTTP 401" in text
        assert "unavailable" in text

    def test_full_tavily_usage(self):
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
        text = info.format()
        assert "tavily" in text
        assert "142 / 1000" in text
        assert "858" in text
        assert "2026-05-01" in text
        assert "Search: 120" in text
        assert "Extract: 15" in text
        assert "Crawl: 7" in text

    def test_usage_without_limit(self):
        info = SearchUsageInfo(provider="tavily", supported=True, used=50)
        text = info.format()
        assert "50 requests" in text
        assert "/" not in text.split("Usage:")[1].split("\n")[0]

    def test_no_breakdown_when_none(self):
        info = SearchUsageInfo(
            provider="tavily", supported=True, used=10, limit=100, remaining=90
        )
        text = info.format()
        assert "Breakdown" not in text

    def test_brave_unsupported(self):
        info = SearchUsageInfo(provider="brave", supported=False)
        text = info.format()
        assert "brave" in text
        assert "not available" in text


# ---------------------------------------------------------------------------
# _parse_tavily_usage tests
# ---------------------------------------------------------------------------

class TestParseTavilyUsage:
    def test_full_response(self):
        data = {
            "used": 142,
            "limit": 1000,
            "remaining": 858,
            "reset_date": "2026-05-01",
            "breakdown": {"search": 120, "extract": 15, "crawl": 7},
        }
        info = _parse_tavily_usage(data)
        assert info.provider == "tavily"
        assert info.supported is True
        assert info.used == 142
        assert info.limit == 1000
        assert info.remaining == 858
        assert info.reset_date == "2026-05-01"
        assert info.search_used == 120
        assert info.extract_used == 15
        assert info.crawl_used == 7

    def test_remaining_computed_when_missing(self):
        data = {"used": 300, "limit": 1000}
        info = _parse_tavily_usage(data)
        assert info.remaining == 700

    def test_remaining_not_negative(self):
        data = {"used": 1100, "limit": 1000}
        info = _parse_tavily_usage(data)
        assert info.remaining == 0

    def test_camel_case_reset_date(self):
        data = {"used": 10, "limit": 100, "resetDate": "2026-06-01"}
        info = _parse_tavily_usage(data)
        assert info.reset_date == "2026-06-01"

    def test_empty_response(self):
        info = _parse_tavily_usage({})
        assert info.provider == "tavily"
        assert info.supported is True
        assert info.used is None
        assert info.limit is None

    def test_no_breakdown_key(self):
        data = {"used": 5, "limit": 50}
        info = _parse_tavily_usage(data)
        assert info.search_used is None
        assert info.extract_used is None
        assert info.crawl_used is None


# ---------------------------------------------------------------------------
# fetch_search_usage routing tests
# ---------------------------------------------------------------------------

class TestFetchSearchUsageRouting:
    @pytest.mark.asyncio
    async def test_duckduckgo_returns_unsupported(self):
        info = await fetch_search_usage("duckduckgo")
        assert info.provider == "duckduckgo"
        assert info.supported is False

    @pytest.mark.asyncio
    async def test_searxng_returns_unsupported(self):
        info = await fetch_search_usage("searxng")
        assert info.supported is False

    @pytest.mark.asyncio
    async def test_jina_returns_unsupported(self):
        info = await fetch_search_usage("jina")
        assert info.supported is False

    @pytest.mark.asyncio
    async def test_brave_returns_unsupported(self):
        info = await fetch_search_usage("brave")
        assert info.provider == "brave"
        assert info.supported is False

    @pytest.mark.asyncio
    async def test_unknown_provider_returns_unsupported(self):
        info = await fetch_search_usage("some_unknown_provider")
        assert info.supported is False

    @pytest.mark.asyncio
    async def test_tavily_no_api_key_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            # Ensure TAVILY_API_KEY is not set
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
            "used": 142,
            "limit": 1000,
            "remaining": 858,
            "reset_date": "2026-05-01",
            "breakdown": {"search": 120, "extract": 15, "crawl": 7},
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
        assert info.reset_date == "2026-05-01"
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


# ---------------------------------------------------------------------------
# build_status_content integration tests
# ---------------------------------------------------------------------------

class TestBuildStatusContentWithSearchUsage:
    _BASE_KWARGS = dict(
        version="0.1.0",
        model="claude-opus-4-5",
        start_time=1_000_000.0,
        last_usage={"prompt_tokens": 1000, "completion_tokens": 200},
        context_window_tokens=65536,
        session_msg_count=5,
        context_tokens_estimate=3000,
    )

    def test_no_search_usage_unchanged(self):
        """Omitting search_usage_text keeps existing behaviour."""
        content = build_status_content(**self._BASE_KWARGS)
        assert "🔍" not in content
        assert "Web Search" not in content

    def test_search_usage_none_unchanged(self):
        content = build_status_content(**self._BASE_KWARGS, search_usage_text=None)
        assert "🔍" not in content

    def test_search_usage_appended(self):
        usage_text = "🔍 Web Search: tavily\n   Usage: 142 / 1000 requests"
        content = build_status_content(**self._BASE_KWARGS, search_usage_text=usage_text)
        assert "🔍 Web Search: tavily" in content
        assert "142 / 1000" in content

    def test_existing_fields_still_present(self):
        usage_text = "🔍 Web Search: duckduckgo\n   Usage tracking: not available"
        content = build_status_content(**self._BASE_KWARGS, search_usage_text=usage_text)
        # Original fields must still be present
        assert "nanobot v0.1.0" in content
        assert "claude-opus-4-5" in content
        assert "1000 in / 200 out" in content
        # New field appended
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
        content = build_status_content(**self._BASE_KWARGS, search_usage_text=info.format())
        assert "142 / 1000" in content
        assert "858" in content
        assert "2026-05-01" in content
        assert "Search: 120" in content
