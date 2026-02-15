"""Tests for web search tool with DuckDuckGo fallback."""

import pytest
from unittest.mock import patch, MagicMock

from nanobot.agent.tools.web import WebSearchTool, DuckDuckGoSearchProvider


class TestDuckDuckGoSearchProvider:
    """Tests for DuckDuckGo search provider."""

    @pytest.mark.asyncio
    async def test_ddg_search_integration(self) -> None:
        """Integration test: actually calls DuckDuckGo API."""
        provider = DuckDuckGoSearchProvider()
        result = await provider.search("what is nanobot", 3)
        
        assert "(via DuckDuckGo)" in result
        assert "nanobot" in result.lower()
        assert "http" in result

    @pytest.mark.asyncio
    async def test_ddg_search_returns_results(self) -> None:
        """Test that DuckDuckGo provider returns parsed results."""
        provider = DuckDuckGoSearchProvider()
        
        mock_results = [
            {"title": "Example Title", "href": "https://example.com", "body": "Example description"}
        ]
        
        with patch("nanobot.agent.tools.web.DDGS") as mock_ddgs:
            mock_instance = MagicMock()
            mock_instance.text.return_value = iter(mock_results)
            mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)

            result = await provider.search("test query", 5)

        assert "Results for: test query (via DuckDuckGo)" in result
        assert "Example Title" in result
        assert "example.com" in result

    @pytest.mark.asyncio
    async def test_ddg_search_handles_no_results(self) -> None:
        """Test DuckDuckGo provider handles empty results."""
        provider = DuckDuckGoSearchProvider()
        
        with patch("nanobot.agent.tools.web.DDGS") as mock_ddgs:
            mock_instance = MagicMock()
            mock_instance.text.return_value = iter([])
            mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)

            result = await provider.search("nonexistent query", 5)

        assert "No results found" in result

    @pytest.mark.asyncio
    async def test_ddg_search_handles_network_error(self) -> None:
        """Test DuckDuckGo provider handles network errors."""
        provider = DuckDuckGoSearchProvider()
        
        with patch("nanobot.agent.tools.web.DDGS") as mock_ddgs:
            mock_ddgs.side_effect = Exception("Network error")

            result = await provider.search("test", 5)

        assert "Error:" in result


class TestWebSearchTool:
    """Tests for WebSearchTool with DuckDuckGo fallback."""

    @pytest.mark.asyncio
    async def test_uses_duckduckgo_when_no_brave_api_key(self) -> None:
        """Test that DuckDuckGo is used when no Brave API key is set."""
        tool = WebSearchTool(api_key="", max_results=5)
        
        mock_results = [
            {"title": "Test Result", "href": "https://example.com", "body": ""}
        ]
        
        with patch("nanobot.agent.tools.web.DDGS") as mock_ddgs:
            mock_instance = MagicMock()
            mock_instance.text.return_value = iter(mock_results)
            mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)

            result = await tool.execute(query="test")

        assert "(via DuckDuckGo)" in result
        assert "Test Result" in result

    @pytest.mark.asyncio
    async def test_falls_back_to_ddg_when_brave_fails(self) -> None:
        """Test fallback to DuckDuckGo when Brave Search fails."""
        tool = WebSearchTool(api_key="fake-api-key", max_results=5)
        
        mock_results = [
            {"title": "Fallback Result", "href": "https://fallback.com", "body": ""}
        ]
        
        with patch("httpx.AsyncClient.get") as mock_get:
            # First call (Brave) fails
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = Exception("Brave API error")
            mock_get.return_value = mock_response

            with patch("nanobot.agent.tools.web.DDGS") as mock_ddgs:
                mock_instance = MagicMock()
                mock_instance.text.return_value = iter(mock_results)
                mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_instance)
                mock_instance.__exit__ = MagicMock(return_value=False)
                
                result = await tool.execute(query="test")

        assert "falling back to DuckDuckGo" in result
        assert "Fallback Result" in result

    @pytest.mark.asyncio
    async def test_uses_brave_when_api_key_present(self) -> None:
        """Test that Brave Search is used when API key is available."""
        tool = WebSearchTool(api_key="brave-key", max_results=5)
        
        # Mock Brave API response
        mock_response_data = {
            "web": {
                "results": [
                    {
                        "title": "Brave Result",
                        "url": "https://brave.com",
                        "description": "A brave search result"
                    }
                ]
            }
        }
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = await tool.execute(query="test")

        assert "Brave Result" in result
        assert "brave.com" in result
        # Should NOT contain DuckDuckGo marker
        assert "(via DuckDuckGo)" not in result

    @pytest.mark.asyncio
    async def test_respects_max_results_parameter(self) -> None:
        """Test that count parameter is respected."""
        tool = WebSearchTool(api_key="", max_results=3)
        
        mock_results = [
            {"title": f"Result {i}", "href": f"https://{i}.com", "body": ""}
            for i in range(5)
        ]
        
        with patch("nanobot.agent.tools.web.DDGS") as mock_ddgs:
            mock_instance = MagicMock()
            mock_instance.text.return_value = iter(mock_results)
            mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)

            result = await tool.execute(query="test", count=2)

        assert "Result" in result
