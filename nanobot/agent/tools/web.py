"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks

# Try to import DuckDuckGo search library
try:
    from duckduckgo_search import DDGS
    DDG_AVAILABLE = True
except ImportError:
    DDG_AVAILABLE = False


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


class WebSearchTool(Tool):
    """Search web using DuckDuckGo (default) with optional Brave API support."""

    name = "web_search"
    description = "Search web using multiple engines. Returns titles, URLs, and snippets. Engine options: 'ddg' (DuckDuckGo - general search, default), 'wikipedia' (encyclopedic/factual information), 'searxng' (aggregated search), 'brave' (privacy-focused, requires API key), 'combine' (all engines)."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10},
            "engine": {"type": "string", "description": "Search engine: 'ddg' (default, general web), 'wikipedia' (factual/encyclopedic), 'searxng' (aggregated), 'brave' (requires API key), 'combine' (all engines)", "enum": ["ddg", "wikipedia", "searxng", "brave", "combine"]}
        },
        "required": ["query"]
    }

    def __init__(self, api_key: str | None = None, max_results: int = 5, engine: str = "ddg"):
        """
        Initialize web search tool.

        Args:
            api_key: Brave Search API key (optional, for Brave engine)
            max_results: Maximum number of results to return
            engine: Search engine to use - "ddg" (default), "brave", "searxng", "wikipedia", "combine"
                       - "ddg": Use DuckDuckGo - free, no API key needed (default)
                       - "brave": Use Brave API - requires api_key
                       - "searxng": Use SearXNG - free, no API key needed
                       - "wikipedia": Use Wikipedia - free, no API key needed
                       - "combine": Search all available engines and combine results
        """
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self.max_results = max_results
        self.engine = engine.lower()
        self._ddg_available = DDG_AVAILABLE

    async def _search_brave(self, query: str, n: int) -> str | None:
        """Try searching with Brave API."""
        if not self.api_key:
            return None

        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    timeout=10.0
                )
                r.raise_for_status()

            results = r.json().get("web", {}).get("results", [])
            if not results:
                return None

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except Exception:
            return None

    async def _search_ddg(self, query: str, n: int) -> str | None:
        """Try searching with DuckDuckGo."""
        if not self._ddg_available:
            return None

        try:
            ddgs = DDGS()
            results = ddgs.text(query, max_results=n)

            if not results:
                return None

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('link', '')}")
                if body := item.get("body"):
                    lines.append(f"   {body}")
            return "\n".join(lines)
        except Exception:
            return None

    async def _search_searxng(self, query: str, n: int) -> str | None:
        """Try searching with SearXNG."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                        "https://searx.ng/search",
                        params={
                            "q": query,
                            "format": "json",
                            "engines": "google,bing,duckduckgo,brave"
                        },
                        timeout=10.0
                    )
                    r.raise_for_status()

            results = r.json().get("results", [])
            if not results:
                return None

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                title = item.get("title", "")
                url = item.get("url", "")
                snippet = item.get("content", "")[:100]
                lines.append(f"{i}. {title}\n   {url}")
                if snippet:
                    lines.append(f"   {snippet}")
            return "\n".join(lines)
        except Exception:
            return None

    async def _search_wikipedia(self, query: str, n: int) -> str | None:
        """Try searching with Wikipedia."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                            "https://en.wikipedia.org/w/api.php",
                            params={
                                "action": "query",
                                "list": "search",
                                "srsearch": query,
                                "srlimit": n,
                                "format": "json"
                            },
                            timeout=10.0
                        )
                    r.raise_for_status()

            results = r.json().get("query", {}).get("search", [])
            if not results:
                return None

            lines = [f"Wikipedia results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                title = item.get("title", "")
                snippet = item.get("snippet", "")[:200]
                lines.append(f"{i}. {title}\n   {snippet}")
            return "\n".join(lines)
        except Exception:
            return None

    async def _search_engine(self, engine: str, query: str, n: int) -> str | None:
        """Search using specified engine."""
        if engine == "brave":
            return await self._search_brave(query, n)
        elif engine == "ddg":
            return await self._search_ddg(query, n)
        elif engine == "searxng":
            return await self._search_searxng(query, n)
        elif engine == "wikipedia":
            return await self._search_wikipedia(query, n)
        return None

    async def execute(self, query: str, count: int | None = None, engine: str | None = None, **kwargs: Any) -> str:
        n = min(max(count or self.max_results, 1), 10)

        # Use engine from parameter if provided, otherwise use default
        search_engine = (engine or self.engine).lower()

        # Combine mode: search all engines
        if search_engine == "combine":
            engine_results = {}
            for engine in ["ddg", "searxng", "wikipedia", "brave"]:
                engine_results[engine] = await self._search_engine(engine, query, n)

            if any(engine_results.values()):
                combined = []
                for eng, res in engine_results.items():
                    combined.extend(res or [])
                return "\n".join(combined)
            return "Error: All search engines failed. Try installing duckduckgo-search or check your internet connection."

        # Single engine mode
        result = await self._search_engine(search_engine, query, n)

        if result:
            return result
        elif search_engine == "brave":
            return "Error: Brave search failed. Check your API key."
        return f"Error: {search_engine} search failed. Try installing duckduckgo-search or check your internet connection."


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
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', html, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', html, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
