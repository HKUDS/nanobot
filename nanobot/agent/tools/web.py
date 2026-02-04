"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
import ipaddress
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  
DEFAULT_TIMEOUT = 30.0

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


def _is_private_host(hostname: str) -> bool:
    """Block private / loopback IPs to prevent SSRF."""
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        # Not an IP (domain name) → allowed
        return False


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: scheme, domain, SSRF safety."""
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False, "Only http/https URLs are allowed"

        if not parsed.hostname:
            return False, "Missing hostname"

        if _is_private_host(parsed.hostname):
            return False, "Private or local network addresses are not allowed"

        return True, ""
    except Exception as e:
        return False, str(e)
    
class WebSearchTool(Tool):
    """Search the web using Brave Search API."""

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self._api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self._max_results = max_results

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the web and return titles, URLs, and snippets."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {
                    "type": "integer",
                    "description": "Number of results (1-10)",
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self._api_key:
            return "Error: BRAVE_API_KEY not configured"

        try:
            n = min(max(count or self._max_results, 1), 10)

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": self._api_key,
                        "User-Agent": USER_AGENT,
                    },
                )
                response.raise_for_status()

            results = response.json().get("web", {}).get("results", [])
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}")
                lines.append(f"   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")

            return "\n".join(lines)
        except Exception as e:
            return f"Error during web search: {str(e)}"

class WebFetchTool(Tool):
    """Fetch and extract readable content from a URL."""

    def __init__(self, max_chars: int = 50_000):
        self._max_chars = max_chars

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Fetch a URL and extract readable content as markdown or text."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "extractMode": {
                    "type": "string",
                    "enum": ["markdown", "text"],
                    "default": "markdown",
                },
                "maxChars": {"type": "integer", "minimum": 100},
            },
            "required": ["url"],
        }

    async def execute(
        self,
        url: str,
        extractMode: str = "markdown",
        maxChars: int | None = None,
        **kwargs: Any,
    ) -> str:
        is_valid, error = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": error, "url": url})

        try:
            try:
                from readability import Document
            except ImportError:
                return json.dumps({"error": "readability-lxml not installed", "url": url})

            max_chars = maxChars or self._max_chars

            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=DEFAULT_TIMEOUT,
            ) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html,application/json",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            extractor = "raw"

            # JSON response
            if "application/json" in content_type:
                text = json.dumps(response.json(), indent=2)
                extractor = "json"

            # HTML response
            elif "text/html" in content_type or response.text[:256].lower().startswith(
                ("<!doctype", "<html")
            ):
                doc = Document(response.text)
                body = (
                    self._to_markdown(doc.summary())
                    if extractMode == "markdown"
                    else _strip_tags(doc.summary())
                )
                text = f"# {doc.title()}\n\n{body}" if doc.title() else body
                extractor = "readability"

            else:
                text = response.text

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps(
                {
                    "url": url,
                    "finalUrl": str(response.url),
                    "status": response.status_code,
                    "extractor": extractor,
                    "truncated": truncated,
                    "length": len(text),
                    "text": text,
                }
            )

        except Exception as e:
            return json.dumps({"error": str(e), "url": url})

    def _to_markdown(self, html_text: str) -> str:
        """Convert HTML to markdown."""
        text = re.sub(
            r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
            lambda m: f"[{_strip_tags(m[2])}]({m[1]})",
            html_text,
            flags=re.I,
        )
        text = re.sub(
            r"<h([1-6])[^>]*>([\s\S]*?)</h\1>",
            lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n',
            text,
            flags=re.I,
        )
        text = re.sub(
            r"<li[^>]*>([\s\S]*?)</li>",
            lambda m: f"\n- {_strip_tags(m[1])}",
            text,
            flags=re.I,
        )
        text = re.sub(r"</(p|div|section|article)>", "\n\n", text, flags=re.I)
        text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.I)
        return _normalize(_strip_tags(text))