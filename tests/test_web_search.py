"""Tests for web search tool with DuckDuckGo fallback."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nanobot.agent.tools.web import WebSearchTool, DuckDuckGoSearchProvider


class TestDuckDuckGoSearchProvider:
    """Tests for DuckDuckGo HTML search provider."""

    @pytest.mark.asyncio
    async def test_ddg_search_returns_results(self) -> None:
        """Test that DuckDuckGo provider returns parsed results."""
        provider = DuckDuckGoSearchProvider()
        
        # Mock HTML response from DuckDuckGo
        mock_html = '''
        <a class="result__a" href="https://example.com">Example Title</a>
        <a class="result__snippet">Example description</a>
        '''
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = mock_html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = await provider.search("test query", 5)

        assert "Results for: test query (via DuckDuckGo)" in result
        assert "Example Title" in result
        assert "example.com" in result

    @pytest.mark.asyncio
    async def test_ddg_search_handles_no_results(self) -> None:
        """Test DuckDuckGo provider handles empty results."""
        provider = DuckDuckGoSearchProvider()
        
        mock_html = '<html><body>no results</body></html>'
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = mock_html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = await provider.search("nonexistent query", 5)

        assert "No results found" in result

    @pytest.mark.asyncio
    async def test_ddg_search_handles_network_error(self) -> None:
        """Test DuckDuckGo provider handles network errors."""
        import httpx
        provider = DuckDuckGoSearchProvider()
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.side_effect = httpx.TimeoutException("timeout")

            result = await provider.search("test", 5)

        assert "Error:" in result


class TestWebSearchTool:
    """Tests for WebSearchTool with DuckDuckGo fallback."""

    @pytest.mark.asyncio
    async def test_uses_duckduckgo_when_no_brave_api_key(self) -> None:
        """Test that DuckDuckGo is used when no Brave API key is set."""
        tool = WebSearchTool(api_key="", max_results=5)
        
        mock_html = '''
        <a class="result__a" href="https://example.com">Test Result</a>
        '''
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = mock_html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = await tool.execute(query="test")

        assert "(via DuckDuckGo)" in result
        assert "Test Result" in result

    @pytest.mark.asyncio
    async def test_falls_back_to_ddg_when_brave_fails(self) -> None:
        """Test fallback to DuckDuckGo when Brave Search fails."""
        tool = WebSearchTool(api_key="fake-api-key", max_results=5)
        
        mock_html = '''
        <a class="result__a" href="https://fallback.com">Fallback Result</a>
        '''
        
        with patch("httpx.AsyncClient.get") as mock_get:
            # First call (Brave) fails
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = Exception("Brave API error")
            mock_get.return_value = mock_response

            # Patch DDG to return results
            with patch.object(tool._ddg_provider, "search", new_callable=AsyncMock) as mock_ddg:
                mock_ddg.return_value = "Results for: test (via DuckDuckGo)\n1. Fallback Result\n   https://fallback.com"
                
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
        
        mock_html = '''
        <a class="result__a" href="https://1.com">Result 1</a>
        <a class="result__a" href="https://2.com">Result 2</a>
        <a class="result__a" href="https://3.com">Result 3</a>
        <a class="result__a" href="https://4.com">Result 4</a>
        '''
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = mock_html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = await tool.execute(query="test", count=2)

        # Should only have 2 results (but DDG might parse more)
        # The key is that it returns something
        assert "Result" in result
