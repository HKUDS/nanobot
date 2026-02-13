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


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


class WebSearchTool(Tool):
    """Search the web using Brave Search API."""

    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {
                "type": "integer",
                "description": "Results (1-10)",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 5,
        provider: str = "brave",
        ollama_api_key: str | None = None,
        ollama_api_base: str | None = None,
    ):
        self.provider = provider
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self.max_results = max_results
        self.ollama_api_key = ollama_api_key or os.environ.get(
            "OLLAMA_API_KEY", "")
        self.ollama_api_base = (
            ollama_api_base or "https://ollama.com").rstrip("/")

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        n = min(max(count or self.max_results, 1), 10)

        if self.provider == "ollama":
            return await self._ollama_search(query, n)
        if self.provider == "hybrid":
            result = await self._brave_search(query, n)
            if not result.startswith("Error:") and not result.startswith("No results"):
                return result
            return await self._ollama_search(query, n)
        return await self._brave_search(query, n)

    async def _brave_search(self, query: str, n: int) -> str:
        if not self.api_key:
            return "Error: BRAVE_API_KEY not configured"

        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json",
                             "X-Subscription-Token": self.api_key},
                    timeout=10.0,
                )
                r.raise_for_status()

            results = r.json().get("web", {}).get("results", [])
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(
                    f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    async def _ollama_search(self, query: str, n: int) -> str:
        if not self.ollama_api_key:
            return "Error: OLLAMA_API_KEY not configured for Ollama web_search"

        endpoint = f"{self.ollama_api_base}/api/web_search"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    endpoint,
                    json={"query": query, "max_results": n},
                    headers={"Authorization": f"Bearer {self.ollama_api_key}"},
                    timeout=15.0,
                )
                r.raise_for_status()

            results = r.json().get("results", [])
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(
                    f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("content"):
                    lines.append(f"   {desc}")
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
            "maxChars": {"type": "integer", "minimum": 100},
        },
        "required": ["url"],
    }

    def __init__(
        self,
        max_chars: int = 50000,
        provider: str = "nanobot",
        ollama_api_key: str | None = None,
        ollama_api_base: str | None = None,
    ):
        self.max_chars = max_chars
        self.provider = provider
        self.ollama_api_key = ollama_api_key or os.environ.get(
            "OLLAMA_API_KEY", "")
        self.ollama_api_base = (
            ollama_api_base or "https://ollama.com").rstrip("/")

    async def execute(
        self,
        url: str,
        extract_mode: str = "markdown",
        max_chars: int | None = None,
        **kwargs: Any,
    ) -> str:
        extract_mode = kwargs.get("extractMode", extract_mode)
        max_chars = kwargs.get("maxChars", max_chars)

        if self.provider == "ollama":
            return await self._ollama_fetch(url, max_chars=max_chars)
        if self.provider == "hybrid":
            result = await self._nanobot_fetch(url, extract_mode, max_chars)
            if not result.startswith('{"error"'):
                return result
            return await self._ollama_fetch(url, max_chars=max_chars)
        return await self._nanobot_fetch(url, extract_mode, max_chars)

    async def _nanobot_fetch(
        self,
        url: str,
        extract_mode: str = "markdown",
        max_chars: int | None = None,
    ) -> str:
        from readability import Document

        max_chars = max_chars or self.max_chars

        # Validate URL before fetching
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url})

        try:
            async with httpx.AsyncClient(
                follow_redirects=True, max_redirects=MAX_REDIRECTS, timeout=30.0
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
                content = (
                    self._to_markdown(doc.summary())
                    if extract_mode == "markdown"
                    else _strip_tags(doc.summary())
                )
                text = f"# {doc.title()}\n\n{content}" if doc.title(
                ) else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps(
                {
                    "url": url,
                    "finalUrl": str(r.url),
                    "status": r.status_code,
                    "extractor": extractor,
                    "truncated": truncated,
                    "length": len(text),
                    "text": text,
                }
            )
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})

    async def _ollama_fetch(self, url: str, max_chars: int | None = None) -> str:
        if not self.ollama_api_key:
            return json.dumps(
                {"error": "OLLAMA_API_KEY not configured for Ollama web_fetch", "url": url}
            )

        resolved_max_chars = self.max_chars if max_chars is None else max_chars
        endpoint = f"{self.ollama_api_base}/api/web_fetch"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    endpoint,
                    json={"url": url},
                    headers={
                        "Authorization": f"Bearer {self.ollama_api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=20.0,
                )
                r.raise_for_status()

            payload = r.json()
            content = payload.get("content", "")
            truncated = len(content) > resolved_max_chars
            if truncated:
                content = content[:resolved_max_chars]
            return json.dumps(
                {
                    "url": url,
                    "extractor": "ollama_web_fetch",
                    "title": payload.get("title", ""),
                    "links": payload.get("links", []),
                    "truncated": truncated,
                    "length": len(content),
                    "text": content,
                }
            )
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})

    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(
            r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
            lambda m: f"[{_strip_tags(m[2])}]({m[1]})",
            html,
            flags=re.I,
        )
        text = re.sub(
            r"<h([1-6])[^>]*>([\s\S]*?)</h\1>",
            lambda m: f"\n{'#' * int(m[1])} {_strip_tags(m[2])}\n",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"<li[^>]*>([\s\S]*?)</li>", lambda m: f"\n- {_strip_tags(m[1])}", text, flags=re.I
        )
        text = re.sub(r"</(p|div|section|article)>", "\n\n", text, flags=re.I)
        text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.I)
        return _normalize(_strip_tags(text))
