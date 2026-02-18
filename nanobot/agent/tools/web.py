"""Web tools: web_search and web_fetch."""

import asyncio
import html
import json
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx
from ddgs import DDGS
from loguru import logger

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


def _format_results(query: str, items: list[dict[str, Any]], n: int) -> str:
    """Format provider results into a shared plaintext output."""
    if not items:
        return f"No results for: {query}"
    lines = [f"Results for: {query}\n"]
    for i, item in enumerate(items[:n], 1):
        title = _normalize(_strip_tags(item.get('title', '')))
        snippet = _normalize(_strip_tags(item.get('content', '')))
        lines.append(f"{i}. {title}\n   {item.get('url', '')}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


class WebSearchTool(Tool):
    """Search the web using configured provider."""

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
        config: "WebSearchConfig | None" = None,
        transport: httpx.AsyncBaseTransport | None = None,
        ddgs_factory: Callable[[], DDGS] | None = None,
    ):
        from nanobot.config.schema import WebSearchConfig

        self.config = config if config is not None else WebSearchConfig()
        self._transport = transport
        self._ddgs_factory = ddgs_factory or (lambda: DDGS(timeout=10))
        self._provider_dispatch: dict[str, Callable[[str, int], Awaitable[str]]] = {
            "duckduckgo": self._search_duckduckgo,
            "tavily": self._search_tavily,
            "searxng": self._search_searxng,
            "brave": self._search_brave,
        }

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        provider = (self.config.provider or "brave").strip().lower()
        n = min(max(count or self.config.max_results, 1), 10)

        search = self._provider_dispatch.get(provider)
        if search is None:
            return f"Error: unknown search provider '{provider}'"
        return await search(query, n)

    async def _fallback_to_duckduckgo(self, missing_key: str, query: str, n: int) -> str:
        logger.warning("Falling back to DuckDuckGo: {} not configured", missing_key)
        ddg = await self._search_duckduckgo(query=query, n=n)
        if ddg.startswith('Error:'):
            return ddg
        return f'Using DuckDuckGo fallback ({missing_key} missing).\n\n{ddg}'

    async def _search_brave(self, query: str, n: int) -> str:
        api_key = self.config.api_key or os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            if self.config.fallback_to_duckduckgo:
                return await self._fallback_to_duckduckgo('BRAVE_API_KEY', query, n)
            return "Error: BRAVE_API_KEY not configured"

        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                    timeout=10.0,
                )
                r.raise_for_status()

            items = [{"title": x.get("title", ""), "url": x.get("url", ""),
                      "content": x.get("description", "")}
                     for x in r.json().get("web", {}).get("results", [])]
            return _format_results(query, items, n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_tavily(self, query: str, n: int) -> str:
        api_key = self.config.api_key or os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            if self.config.fallback_to_duckduckgo:
                return await self._fallback_to_duckduckgo('TAVILY_API_KEY', query, n)
            return "Error: TAVILY_API_KEY not configured"

        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                r = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"query": query, "max_results": n},
                    timeout=15.0,
                )
                r.raise_for_status()

            results = r.json().get("results", [])
            return _format_results(query, results, n)
        except Exception as e:
            return f"Error: {e}"

    async def _search_duckduckgo(self, query: str, n: int) -> str:
        try:
            ddgs = self._ddgs_factory()
            raw_results = await asyncio.to_thread(ddgs.text, query, max_results=n)

            if not raw_results:
                return f"No results for: {query}"

            items = [
                {
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "content": result.get("body", ""),
                }
                for result in raw_results
            ]
            return _format_results(query, items, n)
        except Exception as e:
            logger.warning("DuckDuckGo search failed: {}", e)
            return f"Error: DuckDuckGo search failed ({e})"

    async def _search_searxng(self, query: str, n: int) -> str:
        base_url = (self.config.base_url or os.environ.get("SEARXNG_BASE_URL", "")).strip()
        if not base_url:
            if self.config.fallback_to_duckduckgo:
                return await self._fallback_to_duckduckgo('SEARXNG_BASE_URL', query, n)
            return "Error: SEARXNG_BASE_URL not configured"

        endpoint = f"{base_url.rstrip('/')}/search"
        is_valid, error_msg = _validate_url(endpoint)
        if not is_valid:
            return f"Error: invalid SearXNG URL: {error_msg}"

        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                r = await client.get(
                    endpoint,
                    params={"q": query, "format": "json"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=10.0,
                )
                r.raise_for_status()

            results = r.json().get("results", [])
            return _format_results(query, results, n)
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
