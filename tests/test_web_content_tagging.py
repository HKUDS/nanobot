"""Tests for untrusted content boundary markers in web tools."""

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from nanobot.agent.tools.web import WebSearchTool, WebFetchTool, _UNTRUSTED_BOUNDARY


class TestWebSearchBoundaryMarkers:
    """Tests that WebSearchTool wraps results with boundary markers."""

    @pytest.mark.asyncio
    async def test_search_results_wrapped_with_boundary(self) -> None:
        tool = WebSearchTool(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "web": {
                "results": [
                    {"title": "Test Result", "url": "https://example.com", "description": "A test result"}
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute("test query")

        assert result.startswith(_UNTRUSTED_BOUNDARY)
        assert result.endswith(_UNTRUSTED_BOUNDARY)
        assert "Test Result" in result

    @pytest.mark.asyncio
    async def test_no_results_not_wrapped(self) -> None:
        """When there are no results, no boundary markers should be added."""
        tool = WebSearchTool(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"web": {"results": []}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute("test query")

        assert _UNTRUSTED_BOUNDARY not in result


class TestWebFetchBoundaryMarkers:
    """Tests that WebFetchTool wraps text content with boundary markers."""

    @pytest.mark.asyncio
    async def test_fetch_text_wrapped_with_boundary(self) -> None:
        tool = WebFetchTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://example.com"
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "Hello, world!"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute("https://example.com", extractMode="text")

        data = json.loads(result)
        assert data["text"].startswith(_UNTRUSTED_BOUNDARY)
        assert data["text"].endswith(_UNTRUSTED_BOUNDARY)
        assert "Hello, world!" in data["text"]

    @pytest.mark.asyncio
    async def test_fetch_error_not_wrapped(self) -> None:
        """Error responses should NOT have boundary markers."""
        tool = WebFetchTool()

        result = await tool.execute("ftp://invalid.com")

        data = json.loads(result)
        assert "error" in data
        assert _UNTRUSTED_BOUNDARY not in result
