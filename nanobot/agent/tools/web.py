"""Web tools: web_search and web_fetch using Exa AI."""

import json
import os
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from nanobot.agent.tools.base import Tool


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


def _get_exa_client(api_key: str) -> "Exa":
    """Create an Exa client with the given API key."""
    from exa_py import Exa
    return Exa(api_key=api_key)


class WebSearchTool(Tool):
    """Search the web using Exa AI."""

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
        self._init_api_key = api_key
        self.max_results = max_results

    @property
    def api_key(self) -> str:
        """Resolve API key at call time so env/config changes are picked up."""
        return self._init_api_key or os.environ.get("EXA_API_KEY", "")

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            return (
                "Error: Exa API key not configured. Set it in "
                "~/.nanobot/config.json under tools.web.search.apiKey "
                "(or export EXA_API_KEY), then restart the gateway."
            )

        try:
            n = min(max(count or self.max_results, 1), 10)
            exa = _get_exa_client(self.api_key)
            result = exa.search(query, num_results=n, type="auto")

            if not result.results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(result.results, 1):
                lines.append(f"{i}. {item.title or ''}\n   {item.url}")
                if item.text:
                    lines.append(f"   {item.text[:200]}")
            return "\n".join(lines)
        except Exception as e:
            logger.error("WebSearch error: {}", e)
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Exa AI."""

    name = "web_fetch"
    description = "Fetch URL and extract readable content."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }

    def __init__(self, api_key: str | None = None, max_chars: int = 50000):
        self._init_api_key = api_key
        self.max_chars = max_chars

    @property
    def api_key(self) -> str:
        """Resolve API key at call time so env/config changes are picked up."""
        return self._init_api_key or os.environ.get("EXA_API_KEY", "")

    async def execute(self, url: str, maxChars: int | None = None, **kwargs: Any) -> str:
        max_chars = maxChars or self.max_chars
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)

        if not self.api_key:
            return json.dumps({"error": "Exa API key not configured. Set EXA_API_KEY or tools.web.search.apiKey.", "url": url}, ensure_ascii=False)

        try:
            exa = _get_exa_client(self.api_key)
            result = exa.get_contents([url], text=True)

            if not result.results:
                return json.dumps({"error": "No content returned", "url": url}, ensure_ascii=False)

            item = result.results[0]
            text = item.text or ""
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps({
                "url": url,
                "finalUrl": item.url or url,
                "extractor": "exa",
                "truncated": truncated,
                "length": len(text),
                "text": text,
            }, ensure_ascii=False)
        except Exception as e:
            logger.error("WebFetch error for {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)
