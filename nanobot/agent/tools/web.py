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
    """Search the web using Brave Search API or a SearXNG instance."""
    
    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    
    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 5,
        config: "WebSearchConfig | None" = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        # Backwards compatible initialization:
        # - legacy callers may pass brave api_key + max_results
        # - preferred: pass Config.tools.web.search as `config`
        from nanobot.config.schema import WebSearchConfig

        self.config: WebSearchConfig = config or WebSearchConfig(
            api_key=api_key or "",
            max_results=max_results,
        )
        if api_key is not None:
            self.config.api_key = api_key
        if max_results != 5:
            self.config.max_results = max_results

        self._transport = transport

    @property
    def parameters(self) -> dict[str, Any]:
        provider = self._resolve_provider()
        return self._tool_parameters_for_provider(provider)

    def _resolve_provider(self) -> str:
        provider = (self.config.provider or "brave").strip().lower()
        if provider not in {"brave", "searxng", "auto"}:
            return "brave"
        if provider == "auto":
            return "searxng" if self._searxng_base_url() else "brave"
        return provider

    def _brave_api_key(self) -> str:
        return self.config.api_key or os.environ.get("BRAVE_API_KEY", "")

    def _searxng_base_url(self) -> str:
        return (
            self.config.searxng.base_url
            or os.environ.get("SEARXNG_BASE_URL", "")
            or os.environ.get("SEARXNG_URL", "")
        ).strip()

    def _searxng_api_key(self) -> str:
        return (self.config.searxng.api_key or os.environ.get("SEARXNG_API_KEY", "")).strip()

    def _searxng_endpoint(self) -> str:
        base_url = self._searxng_base_url()
        if not base_url:
            return ""
        base_url = base_url.rstrip("/")
        if base_url.endswith("/search"):
            return base_url
        return f"{base_url}/search"

    def _tool_parameters_for_provider(self, provider: str) -> dict[str, Any]:
        # Keep tool definitions aligned with the actually configured provider so
        # the LLM does not try to pass irrelevant SearXNG-only parameters when
        # Brave is in use (or vice versa).
        base: dict[str, Any] = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {
                    "type": "integer",
                    "description": "Results (1-10)",
                    "minimum": 1,
                    "maximum": 10,
                    "default": min(max(int(self.config.max_results or 5), 1), 10),
                },
            },
            "required": ["query"],
        }

        if provider != "searxng":
            return base

        cfg = self.config.searxng
        props = base["properties"]
        props.update(
            {
                "language": {"type": "string", "description": "Language hint (e.g. 'en')"},
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "SearXNG categories",
                },
                "time_range": {"type": "string", "description": "SearXNG time range (e.g. day/week/month/year)"},
                "safesearch": {"type": "integer", "description": "SearXNG safesearch level"},
                "engines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "SearXNG engines (optional)",
                },
            }
        )

        # Add defaults only when they are configured; avoid default=null for non-nullable types.
        if cfg.language:
            props["language"]["default"] = cfg.language
        if cfg.categories:
            props["categories"]["default"] = cfg.categories
        if cfg.time_range:
            props["time_range"]["default"] = cfg.time_range
        if cfg.safesearch is not None:
            props["safesearch"]["default"] = cfg.safesearch
        if cfg.engines:
            props["engines"]["default"] = cfg.engines

        return base

    def to_schema(self) -> dict[str, Any]:
        provider = self._resolve_provider()
        description = (
            "Search the web using Brave Search API. Returns titles, URLs, and snippets."
            if provider == "brave"
            else "Search the web using a SearXNG instance. Returns titles, URLs, and snippets."
        )
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": self._tool_parameters_for_provider(provider),
            },
        }
    
    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        provider = self._resolve_provider()
        n = min(max(count or self.config.max_results, 1), 10)

        if provider == "brave":
            return await self._search_brave(query=query, n=n)
        if provider == "searxng":
            return await self._search_searxng(query=query, n=n, **kwargs)

        return f"Error: Unknown web search provider '{provider}'"

    async def _search_brave(self, query: str, n: int) -> str:
        api_key = self._brave_api_key()
        if not api_key:
            return "Error: Brave search not configured (set tools.web.search.apiKey or BRAVE_API_KEY)"

        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                    timeout=10.0,
                )
                r.raise_for_status()

            results = r.json().get("web", {}).get("results", [])
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    async def _search_searxng(
        self,
        query: str,
        n: int,
        language: str | None = None,
        categories: list[str] | None = None,
        time_range: str | None = None,
        safesearch: int | None = None,
        engines: list[str] | None = None,
        **_: Any,
    ) -> str:
        endpoint = self._searxng_endpoint()
        if not endpoint:
            return "Error: SearXNG not configured (set tools.web.search.searxng.baseUrl or SEARXNG_URL)"

        cfg = self.config.searxng
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
        }

        if (lang := (language or cfg.language)) and lang.strip():
            params["language"] = lang.strip()

        cats = categories if categories is not None else cfg.categories
        if cats:
            params["categories"] = ",".join([c for c in cats if c and c.strip()])

        if (tr := (time_range or cfg.time_range)) and tr.strip():
            params["time_range"] = tr.strip()

        ss = safesearch if safesearch is not None else cfg.safesearch
        if ss is not None:
            params["safesearch"] = ss

        engs = engines if engines is not None else cfg.engines
        if engs:
            params["engines"] = ",".join([e for e in engs if e and e.strip()])

        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if api_key := self._searxng_api_key():
            headers["Authorization"] = api_key if api_key.startswith("Bearer ") else f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=cfg.timeout_s) as client:
                r = await client.get(endpoint, params=params, headers=headers)
                r.raise_for_status()
                data = r.json()

            results = data.get("results", []) or []
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                title = _strip_tags(item.get("title") or "").strip()
                url = (item.get("url") or "").strip()
                snippet = _normalize(_strip_tags(item.get("content") or item.get("snippet") or "")).strip()
                lines.append(f"{i}. {title}\n   {url}")
                if snippet:
                    lines.append(f"   {snippet}")
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
