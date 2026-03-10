"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult

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
    """Search the web using Brave Search API."""

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

    def __init__(self, api_key: str | None = None, max_results: int = 5, proxy: str | None = None):
        self._init_api_key = api_key
        self.max_results = max_results
        self.proxy = proxy

    @property
    def api_key(self) -> str:
        """Resolve API key at call time so env/config changes are picked up."""
        return self._init_api_key or os.environ.get("BRAVE_API_KEY", "")

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str | ToolResult:
        if not self.api_key:
            return (
                "Error: Brave Search API key not configured. Set it in "
                "~/.nanobot/config.json under tools.web.search.apiKey "
                "(or export BRAVE_API_KEY), then restart the gateway."
            )

        try:
            n = min(max(count or self.max_results, 1), 10)
            logger.debug("WebSearch: {}", "proxy enabled" if self.proxy else "direct connection")
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    timeout=10.0
                )
                r.raise_for_status()

            results = r.json().get("web", {}).get("results", [])[:n]
            if not results:
                return f"No results for: {query}"

            # Format content for LLM (plain text)
            content_lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                content_lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    content_lines.append(f"   {desc}")
            content = "\n".join(content_lines)

            # Format display for CLI (with more structure)
            display = self._format_search_results(query, results)

            return ToolResult(
                content=content,
                display=display,
                display_type="list_result",
            )
        except httpx.ProxyError as e:
            logger.error("WebSearch proxy error: {}", e)
            return f"Proxy error: {e}"
        except Exception as e:
            logger.error("WebSearch error: {}", e)
            return f"Error: {e}"

    def _format_search_results(self, query: str, results: list[dict]) -> str:
        """
        Format search results for CLI display with background color.

        Args:
            query: Search query string.
            results: List of search result dictionaries.

        Returns:
            Formatted search results with dark gray background and dim text.
        """
        # ANSI color codes - dark gray background with dim foreground
        BG_COLOR = "\x1b[48;2;26;26;26m"   # #1a1a1a
        DIM_FG = "\x1b[38;2;150;150;150m"   # 暗灰色
        BOLD = "\x1b[1m"
        RESET = "\x1b[0m"

        # Get terminal width for full-line background
        try:
            terminal_width = os.get_terminal_size().columns
        except OSError:
            terminal_width = 100

        lines = []

        # Header
        header = f"Search results for: {query}"
        lines.append(f"{BOLD}{BG_COLOR}{DIM_FG}{header}{' ' * (terminal_width - len(header))}{RESET}")
        count = f"Found {len(results)} result{'s' if len(results) != 1 else ''}"
        lines.append(f"{BG_COLOR}{DIM_FG}{count}{' ' * (terminal_width - len(count))}{RESET}")
        # Empty line with background
        lines.append(f"{BG_COLOR}{' ' * terminal_width}{RESET}")

        # Results
        for i, item in enumerate(results, 1):
            title = item.get('title', 'No title')
            url = item.get('url', '')
            desc = item.get('description', '')

            # Title
            title_line = f"{i}. {title}"
            padded = title_line.ljust(terminal_width)
            lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

            # URL
            url_line = f"   {url}"
            padded = url_line.ljust(terminal_width)
            lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

            # Description
            if desc:
                # Truncate long descriptions
                if len(desc) > 200:
                    desc = desc[:197] + "..."
                desc_line = f"   {desc}"
                padded = desc_line.ljust(terminal_width)
                lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

            # Empty line between results
            lines.append(f"{BG_COLOR}{' ' * terminal_width}{RESET}")

        return "\n".join(lines) + "\n"


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

    def __init__(self, max_chars: int = 50000, proxy: str | None = None):
        self.max_chars = max_chars
        self.proxy = proxy

    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str | ToolResult:
        from readability import Document

        max_chars = maxChars or self.max_chars
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            error_json = json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)
            return error_json

        try:
            logger.debug("WebFetch: {}", "proxy enabled" if self.proxy else "direct connection")
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0,
                proxy=self.proxy,
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
                title = "JSON data"
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else _strip_tags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
                title = doc.title() or "Untitled"
            else:
                text, extractor = r.text, "raw"
                title = url.split("/")[-1]

            truncated = len(text) > max_chars
            if truncated: text = text[:max_chars]

            # Content for LLM (JSON format)
            content = json.dumps({
                "url": url,
                "finalUrl": str(r.url),
                "status": r.status_code,
                "extractor": extractor,
                "truncated": truncated,
                "length": len(text),
                "text": text
            }, ensure_ascii=False)

            # Display for CLI (formatted summary)
            display = self._format_fetch_display(url, str(r.url), r.status_code, title, len(text), truncated, extractor)

            return ToolResult(
                content=content,
                display=display,
                display_type="list_result",
            )
        except httpx.ProxyError as e:
            logger.error("WebFetch proxy error for {}: {}", url, e)
            return json.dumps({"error": f"Proxy error: {e}", "url": url}, ensure_ascii=False)
        except Exception as e:
            logger.error("WebFetch error for {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)

    def _format_fetch_display(self, original_url: str, final_url: str, status: int, title: str,
                              length: int, truncated: bool, extractor: str) -> str:
        """
        Format web fetch result for CLI display.

        Args:
            original_url: The requested URL.
            final_url: The final URL after redirects.
            status: HTTP status code.
            title: Page title.
            length: Content length in characters.
            truncated: Whether content was truncated.
            extractor: Extractor type (readability/json/raw).

        Returns:
            Formatted fetch summary for display.
        """
        # ANSI color codes - dark gray background with dim foreground
        BG_COLOR = "\x1b[48;2;26;26;26m"   # #1a1a1a
        DIM_FG = "\x1b[38;2;150;150;150m"   # 暗灰色
        BOLD = "\x1b[1m"
        RESET = "\x1b[0m"

        # Get terminal width for full-line background
        try:
            terminal_width = os.get_terminal_size().columns
        except OSError:
            terminal_width = 100

        lines = []

        # Fetched URL
        url_line = f"Fetched: {original_url}"
        padded = url_line.ljust(terminal_width)
        lines.append(f"{BOLD}{BG_COLOR}{DIM_FG}{padded}{RESET}")

        # Redirected URL
        if final_url != original_url:
            redirect_line = f"Redirected to: {final_url}"
            padded = redirect_line.ljust(terminal_width)
            lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

        # Status
        status_line = f"Status: {status}"
        padded = status_line.ljust(terminal_width)
        lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

        # Title
        title_line = f"Title: {title}"
        padded = title_line.ljust(terminal_width)
        lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

        # Extractor
        extractor_line = f"Extractor: {extractor}"
        padded = extractor_line.ljust(terminal_width)
        lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

        # Length
        length_line = f"Length: {length:,} chars"
        padded = length_line.ljust(terminal_width)
        lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

        # Truncated warning
        if truncated:
            trunc_line = f"⚠️  Content truncated (max {self.max_chars:,} chars)"
            padded = trunc_line.ljust(terminal_width)
            lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

        # Empty line
        lines.append(f"{BG_COLOR}{' ' * terminal_width}{RESET}")

        return "\n".join(lines) + "\n"

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
