"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
import urllib.parse
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


# =============================================================================
# Search Engine Backends
# =============================================================================

class SearchBackend(ABC):
    """Abstract base class for search engine backends."""
    
    @abstractmethod
    async def search(self, query: str, count: int) -> list[dict]:
        """Execute search and return list of results with title, url, snippet."""
        pass
    
    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Check if the backend is available. Returns (available, error_message)."""
        pass


class TavilyBackend(SearchBackend):
    """Tavily Search API - optimized for AI/LLM applications."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "TAVILY_API_KEY not configured. Get one free at https://tavily.com"
        return True, ""
    
    async def search(self, query: str, count: int) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": count,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=15.0
            )
            r.raise_for_status()
        
        data = r.json()
        results = []
        for item in data.get("results", [])[:count]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", "")
            })
        return results


class BraveBackend(SearchBackend):
    """Brave Search API - privacy-focused web search."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "BRAVE_API_KEY not configured. Get one at https://brave.com/search/api/"
        return True, ""
    
    async def search(self, query: str, count: int) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                timeout=10.0
            )
            r.raise_for_status()
        
        results = []
        for item in r.json().get("web", {}).get("results", [])[:count]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", "")
            })
        return results


class DuckDuckGoBackend(SearchBackend):
    """DuckDuckGo HTML search - free, no API key required."""
    
    def is_available(self) -> tuple[bool, str]:
        return True, ""  # Always available, no API key needed
    
    async def search(self, query: str, count: int) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                timeout=15.0
            )
            r.raise_for_status()
        
        return self._parse_html(r.text, count)
    
    def _parse_html(self, html_content: str, max_results: int) -> list[dict]:
        """Parse DuckDuckGo HTML search results."""
        results = []
        
        # Pattern to extract title and URL
        title_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE
        )
        snippet_pattern = re.compile(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE
        )
        
        # Split by result divs
        result_divs = re.split(
            r'<div[^>]*class="[^"]*result[^"]*results_links[^"]*"',
            html_content
        )
        
        for div in result_divs[1:max_results + 1]:
            title_match = title_pattern.search(div)
            snippet_match = snippet_pattern.search(div)
            
            if title_match:
                url = title_match.group(1)
                # Extract actual URL from DuckDuckGo redirect
                if "uddg=" in url:
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                    url = parsed.get("uddg", [url])[0]
                
                title = _strip_tags(title_match.group(2))
                snippet = _strip_tags(snippet_match.group(1)) if snippet_match else ""
                
                if title and url:
                    results.append({"title": title, "url": url, "snippet": snippet})
            
            if len(results) >= max_results:
                break
        
        return results


# =============================================================================
# Main WebSearchTool
# =============================================================================

class WebSearchTool(Tool):
    """Search the web using configurable search engine backend.
    
    Supported engines:
    - tavily (default): AI-optimized search, requires API key from https://tavily.com
    - brave: Privacy-focused search, requires API key from https://brave.com/search/api/
    - duckduckgo: Free search, no API key required
    """
    
    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }
    
    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 5,
        engine: str = "tavily"
    ):
        """Initialize WebSearchTool.
        
        Args:
            api_key: API key for Tavily or Brave (not needed for DuckDuckGo)
            max_results: Default number of results to return
            engine: Search engine to use ("tavily", "brave", or "duckduckgo")
        """
        self.max_results = max_results
        self.engine = engine.lower()
        
        # Resolve API key from parameter or environment
        if api_key:
            self.api_key = api_key
        elif self.engine == "tavily":
            self.api_key = os.environ.get("TAVILY_API_KEY", "")
        else:
            self.api_key = os.environ.get("BRAVE_API_KEY", "")
        
        # Initialize the appropriate backend
        self._backend = self._create_backend()
    
    def _create_backend(self) -> SearchBackend:
        """Create the search backend based on configured engine."""
        if self.engine == "tavily":
            return TavilyBackend(self.api_key)
        elif self.engine == "brave":
            return BraveBackend(self.api_key)
        elif self.engine == "duckduckgo":
            return DuckDuckGoBackend()
        else:
            # Default to Tavily for unknown engines
            return TavilyBackend(self.api_key)
    
    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        # Check if backend is available
        available, error_msg = self._backend.is_available()
        if not available:
            return f"Error: {error_msg}"
        
        try:
            n = min(max(count or self.max_results, 1), 10)
            results = await self._backend.search(query, n)
            
            if not results:
                return f"No results for: {query}"
            
            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                lines.append(f"{i}. {item['title']}\n   {item['url']}")
                if item.get("snippet"):
                    lines.append(f"   {item['snippet']}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""
    
    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }
    
    def __init__(self, max_chars: int = 50000):
        self.max_chars = max_chars
    
    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        from readability import Document

        max_chars = maxChars or self.max_chars

        # Validate URL before fetching
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url})

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
            
            ctype = r.headers.get("content-type", "")
            
            # JSON
            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2), "json"
            # HTML
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else _strip_tags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"
            
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]
            
            return json.dumps({"url": url, "finalUrl": str(r.url), "status": r.status_code,
                              "extractor": extractor, "truncated": truncated, "length": len(text), "text": text})
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})
    
    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
