#web.py
"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse, unquote

import httpx

from nanobot.agent.tools.base import Tool

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5


def _strip_tags(text: str) -> str:
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
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
    """
    Search the web.
    
    Priority order:
    1. Brave Search API (if api_key provided)
    2. DuckDuckGo HTML scraping (no API key needed)
    3. Google HTML scraping (fallback)
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

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self.max_results = max_results

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        n = min(max(count or self.max_results, 1), 10)

        # Build parser list based on available credentials
        parsers = []
        if self.api_key:
            parsers.append(self._brave)
        parsers.extend([self._ddg, self._google])

        # Try each parser in order
        for parser in parsers:
            try:
                results = await parser(query, n)
                if results:
                    return self._format(query, results[:n])
            except Exception:
                continue

        return f"No results for: {query}"

    async def _brave(self, query: str, n: int) -> list[dict]:
        """Search using Brave Search API."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": n},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
                timeout=10.0,
            )
            r.raise_for_status()

        results = []
        for item in r.json().get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        return results

    async def _ddg(self, query: str, n: int) -> list[dict]:
        """Scrape DuckDuckGo HTML version."""
        async with httpx.AsyncClient(follow_redirects=True, max_redirects=MAX_REDIRECTS) as c:
            r = await c.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": USER_AGENT},
                timeout=10.0,
            )
            r.raise_for_status()

        results = []
        for block in re.findall(
            r'<div[^>]*class="[^"]*result\b[^"]*"[^>]*>([\s\S]*?)</div>\s*(?=<div[^>]*class="[^"]*result|$)',
            r.text,
        ):
            m_link = re.search(
                r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>',
                block,
            )
            if not m_link:
                continue

            raw_url = html.unescape(m_link.group(1))
            actual = re.search(r'uddg=([^&]+)', raw_url)
            url = html.unescape(unquote(actual.group(1))) if actual else raw_url
            title = _strip_tags(m_link.group(2))

            m_snip = re.search(
                r'<a[^>]*class="result__snippet"[^>]*>([\s\S]*?)</a>', block
            )
            snippet = _strip_tags(m_snip.group(1)) if m_snip else ""

            if title and url:
                results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= n:
                break

        return results

    async def _google(self, query: str, n: int) -> list[dict]:
        """Fallback: scrape Google search HTML."""
        async with httpx.AsyncClient(follow_redirects=True, max_redirects=MAX_REDIRECTS) as c:
            r = await c.get(
                "https://www.google.com/search",
                params={"q": query, "num": n, "hl": "en"},
                headers={"User-Agent": USER_AGENT},
                timeout=10.0,
            )
            r.raise_for_status()

        results = []
        for m in re.finditer(r'<a[^>]+href="/url\?q=([^&"]+)[^"]*"[^>]*>', r.text):
            url = unquote(m.group(1))
            if not url.startswith("http"):
                continue

            start = m.end()
            chunk = r.text[start:start + 500]
            h3 = re.search(r'<h3[^>]*>([\s\S]*?)</h3>', chunk)
            title = _strip_tags(h3.group(1)) if h3 else url

            span = re.search(r'<span[^>]*>([\s\S]{20,}?)</span>', chunk)
            snippet = _strip_tags(span.group(1)) if span else ""

            results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= n:
                break

        return results

    @staticmethod
    def _format(query: str, results: list[dict]) -> str:
        lines = [f"Results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
        return "\n".join(lines)


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

            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2), "json"
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

    def _to_markdown(self, html_str: str) -> str:
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html_str, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
