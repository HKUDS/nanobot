"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
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
    
    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self._init_api_key = api_key
        self.max_results = max_results

    @property
    def api_key(self) -> str:
        """Resolve API key at call time so env/config changes are picked up."""
        return self._init_api_key or os.environ.get("BRAVE_API_KEY", "")

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            return (
                "Error: Brave Search API key not configured. "
                "Set it in ~/.nanobot/config.json under tools.web.search.apiKey "
                "(or export BRAVE_API_KEY), then restart the gateway."
            )
        
        try:
            n = min(max(count or self.max_results, 1), 10)
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
                return f"No results for: {query}"
            
            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""

    name = "web_fetch"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch (must be from user message)"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }

    _URL_RE = re.compile(r'https?://[^\s<>\"\')]+')

    def __init__(
        self,
        max_chars: int = 50000,
        restrict_to_user_urls: bool = False,
        allowed_domains: list[str] | None = None,
    ):
        self.max_chars = max_chars
        self.restrict_to_user_urls = restrict_to_user_urls
        self._allowed_urls: set[str] = set()
        self._allowed_domains: list[str] = allowed_domains or []

    @property
    def description(self) -> str:
        base = "Fetch URL and extract readable content (HTML → markdown/text). Supports PDF."
        if self.restrict_to_user_urls:
            base += " You can fetch any URL the user includes in their message."
            if self._allowed_domains:
                base += f" You can also fetch from these domains without a user-provided URL: {', '.join(self._allowed_domains)}."
        return base

    @staticmethod
    def _base_url(url: str) -> str:
        """Strip query string and fragment to get scheme + netloc + path."""
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")

    def add_user_urls(self, text: str) -> None:
        """Extract and register URLs from a user message."""
        for url in self._URL_RE.findall(text):
            clean = url.rstrip(".,;:!?)]}\"'")
            self._allowed_urls.add(self._base_url(clean))

    def _is_allowed(self, url: str) -> bool:
        """Check if the URL was provided by the user or matches an allowed domain."""
        if not self.restrict_to_user_urls:
            return True
        # Check pre-registered allowed domains
        try:
            domain = urlparse(url).netloc.lower()
            if any(domain == d or domain.endswith("." + d) for d in self._allowed_domains):
                return True
        except Exception:
            pass
        base = self._base_url(url)
        return any(base.startswith(allowed) for allowed in self._allowed_urls)

    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        from readability import Document

        max_chars = maxChars or self.max_chars

        if not self._is_allowed(url):
            return json.dumps(
                {"error": "URL not allowed — only URLs provided by the user can be fetched.", "url": url},
                ensure_ascii=False,
            )

        # Validate URL before fetching
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                if r.status_code == 403:
                    r = await self._curl_fallback(url)
                else:
                    r.raise_for_status()
            
            ctype = r.headers.get("content-type", "")

            # PDF
            if "application/pdf" in ctype or url.lower().endswith(".pdf"):
                from nanobot.agent.tools.filesystem import _read_pdf
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(r.content)
                    tmp_path = Path(tmp.name)
                try:
                    text, extractor = _read_pdf(tmp_path), "pdf"
                finally:
                    tmp_path.unlink(missing_ok=True)
            # JSON
            elif "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
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
                              "extractor": extractor, "truncated": truncated, "length": len(text), "text": text}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)
    
    @staticmethod
    async def _curl_fallback(url: str) -> httpx.Response:
        """Fall back to curl when httpx is blocked (TLS fingerprinting)."""
        import asyncio
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sL", "-A", USER_AGENT, "-m", "30", url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            raise httpx.HTTPStatusError("curl fallback failed", request=None, response=None)
        r = httpx.Response(200, content=stdout, headers={"content-type": "text/html"})
        r._request = httpx.Request("GET", url)
        return r

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
