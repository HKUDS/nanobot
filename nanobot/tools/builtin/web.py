"""Web tools: web_search and web_fetch."""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import os
import re
import socket
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.tools.base import Tool, ToolResult

# Shared constants
_BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
_BOT_UA = "nanobot/1.0 (compatible; +https://github.com/cgajagon/nanobot)"
USER_AGENT = _BROWSER_UA  # backward compat alias
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks
_BOT_TIMEOUT = 15.0  # Bot endpoints (APIs, plain-text services) are typically fast
_BROWSER_TIMEOUT = 30.0  # HTML pages may be slower
_RETRY_ATTEMPTS = 2  # Total attempts for transient failures
_RETRY_BACKOFF = 1.0  # Seconds between retries
_CACHE_TTL = 300  # 5 min in-memory URL cache
_COMPACT_THRESHOLD = 500  # Output below this length omits verbose metadata
_URL_CACHE_MAX = 200  # C-3: cap LRU cache to prevent unbounded memory growth

# Cloud metadata service hostnames that must never be reachable (SEC-02)
_BLOCKED_HOSTS: frozenset[str] = frozenset(
    {
        "169.254.169.254",  # AWS/GCP/Azure IMDS
        "metadata.google.internal",  # GCP metadata
        "metadata.azure.com",  # Azure IMDS
        "100.100.100.200",  # Alibaba Cloud ECS metadata
    }
)

# In-memory URL cache: url+ua → (timestamp, ToolResult) — LRU-capped at 200 entries (C-3)
_url_cache: OrderedDict[str, tuple[float, ToolResult]] = OrderedDict()

# Shared httpx client — created lazily on first use and reused across calls (LAN-60)
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the module-level shared httpx.AsyncClient, creating it on first call.

    Uses the more conservative browser timeout as the default; per-request
    timeout overrides are passed via ``httpx.Request`` when needed.
    follow_redirects and max_redirects are set here so every fetch benefits
    from redirect following without per-call configuration.
    """
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            timeout=_BROWSER_TIMEOUT,
        )
    return _http_client


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


def _is_private_ip(ip_str: str) -> bool:
    """Return True if the IP address is private, loopback, link-local, or multicast."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
    except ValueError:
        return False


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid non-private domain (SEC-02)."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"

        host = p.hostname or ""

        # Block known cloud metadata service hostnames
        if host in _BLOCKED_HOSTS:
            return False, f"Access to '{host}' is not permitted (cloud metadata service)"

        # If the host is an IP literal, check it immediately without DNS
        if _is_private_ip(host):
            return False, "Access to private/internal addresses is not permitted"

        return True, ""
    except ValueError as e:
        return False, str(e)


async def _check_ssrf_host(host: str) -> str | None:
    """Resolve host and return an error string if it resolves to a private address (SEC-02).

    Returns None if the host is safe, or an error message if it should be blocked.
    DNS failures are ignored — the actual HTTP request will fail naturally.
    """
    if not host:
        return None
    try:
        loop = asyncio.get_event_loop()
        addr_info = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if _is_private_ip(ip_str):
                return f"Access to private/internal addresses is not permitted (resolved {host} → {ip_str})"
    except OSError:
        pass  # DNS failure — let the HTTP request fail naturally
    return None


class WebSearchTool(Tool):
    """Search the web using Brave Search API."""

    readonly = True
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

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self._init_api_key = api_key
        self.max_results = max_results

    @property
    def api_key(self) -> str:
        """Resolve API key at call time so env/config changes are picked up."""
        return self._init_api_key or os.environ.get("BRAVE_API_KEY", "")

    def check_available(self) -> tuple[bool, str | None]:
        if not self.api_key:
            return False, "Brave Search API key not configured"
        return True, None

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        if not self.api_key:
            return ToolResult.fail(
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
                    timeout=10.0,
                )
                r.raise_for_status()

            results = r.json().get("web", {}).get("results", [])
            if not results:
                return ToolResult.ok(f"No results for: {query}")

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return ToolResult.ok("\n".join(lines))
        except Exception as e:  # crash-barrier: third-party httpx + API errors
            return ToolResult.fail(f"Error: {e}")


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""

    readonly = True
    cacheable = True
    summarize = False  # cache for later retrieval but don't replace output with summary

    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text/json)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {
                "type": "string",
                "enum": ["markdown", "text", "json"],
                "default": "markdown",
                "description": (
                    "'markdown' (default): convert HTML to Markdown. "
                    "'text': plain text (tags stripped). "
                    "'json': return raw response body (best for API endpoints)."
                ),
            },
            "maxChars": {"type": "integer", "minimum": 100},
            "userAgent": {
                "type": "string",
                "enum": ["browser", "bot"],
                "default": "browser",
                "description": (
                    "User-Agent mode. 'browser' (default) sends a Chrome-like UA "
                    "for sites that block bots. 'bot' sends a minimal UA — use for "
                    "APIs, weather services (wttr.in), and endpoints that serve "
                    "lighter responses to non-browser clients."
                ),
            },
        },
        "required": ["url"],
    }

    def __init__(self, max_chars: int = 50000):
        self.max_chars = max_chars

    async def execute(  # type: ignore[override]
        self,
        url: str,
        extract_mode: str = "markdown",  # noqa: N803
        max_chars: int | None = None,
        user_agent: str = "browser",
        **kwargs: Any,
    ) -> ToolResult:
        # Accept camelCase from LLM tool calls
        extract_mode = kwargs.pop("extractMode", extract_mode)  # type: ignore[assignment]
        max_chars = kwargs.pop("maxChars", max_chars) or self.max_chars  # type: ignore[assignment]
        user_agent = kwargs.pop("userAgent", user_agent)  # type: ignore[assignment]

        # Validate URL before fetching (scheme, domain, blocked hosts, IP literals)
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return ToolResult.fail(
                json.dumps(
                    {"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False
                )
            )

        # SSRF: async DNS resolution check — block if host resolves to private IP (SEC-02)
        parsed_host = urlparse(url).hostname or ""
        ssrf_error = await _check_ssrf_host(parsed_host)
        if ssrf_error:
            return ToolResult.fail(
                json.dumps(
                    {"error": f"URL validation failed: {ssrf_error}", "url": url},
                    ensure_ascii=False,
                )
            )

        # Check in-memory cache (LRU-capped at _URL_CACHE_MAX entries, C-3)
        cache_key = f"{url}|{user_agent}"
        cached = _url_cache.get(cache_key)
        if cached:
            ts, result = cached
            if time.monotonic() - ts < _CACHE_TTL:
                _url_cache.move_to_end(cache_key)  # LRU: mark as recently used
                return result
            del _url_cache[cache_key]

        ua_string = _BOT_UA if user_agent == "bot" else _BROWSER_UA
        timeout = _BOT_TIMEOUT if user_agent == "bot" else _BROWSER_TIMEOUT

        # Fetch with internal retry for transient failures
        last_err: Exception | None = None
        r: httpx.Response | None = None
        client = _get_http_client()
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                r = await client.get(
                    url,
                    headers={"User-Agent": ua_string},
                    timeout=timeout,
                )
                r.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_err = e
                if attempt < _RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(_RETRY_BACKOFF)
            except httpx.HTTPStatusError as e:
                # Don't retry client errors (4xx), only server errors (5xx)
                if e.response.status_code < 500:
                    return ToolResult.fail(
                        json.dumps({"error": str(e), "url": url}, ensure_ascii=False)
                    )
                last_err = e
                if attempt < _RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(_RETRY_BACKOFF)
            except Exception as e:  # crash-barrier: unexpected httpx errors
                return ToolResult.fail(
                    json.dumps({"error": str(e), "url": url}, ensure_ascii=False)
                )

        if r is None:
            return ToolResult.fail(
                json.dumps({"error": str(last_err), "url": url}, ensure_ascii=False)
            )

        try:
            result = self._extract(r, extract_mode, max_chars, url)
        except Exception as e:  # crash-barrier: readability / markdownify errors
            return ToolResult.fail(json.dumps({"error": str(e), "url": url}, ensure_ascii=False))

        # Store in LRU cache — evict oldest entry if at capacity (C-3)
        _url_cache[cache_key] = (time.monotonic(), result)
        _url_cache.move_to_end(cache_key)
        if len(_url_cache) > _URL_CACHE_MAX:
            _url_cache.popitem(last=False)  # remove oldest

        return result

    def _extract(
        self, r: httpx.Response, extract_mode: str, max_chars: int, url: str
    ) -> ToolResult:
        """Extract content from the HTTP response."""
        from readability import Document

        ctype = r.headers.get("content-type", "")

        # JSON response or explicit json mode — return raw body
        if "application/json" in ctype or extract_mode == "json":
            try:
                text = json.dumps(r.json(), indent=2, ensure_ascii=False)
            except (ValueError, TypeError):
                text = r.text
            extractor = "json"
        # HTML
        elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
            doc = Document(r.text)
            content = (
                self._to_markdown(doc.summary())
                if extract_mode == "markdown"
                else _strip_tags(doc.summary())
            )
            text = f"# {doc.title()}\n\n{content}" if doc.title() else content
            extractor = "readability"
        else:
            text, extractor = r.text, "raw"

        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]

        # Compact output for small responses to save tokens
        if len(text) < _COMPACT_THRESHOLD:
            output = json.dumps(
                {"url": str(r.url), "text": text},
                ensure_ascii=False,
            )
        else:
            output = json.dumps(
                {
                    "url": url,
                    "finalUrl": str(r.url),
                    "status": r.status_code,
                    "extractor": extractor,
                    "truncated": truncated,
                    "length": len(text),
                    "text": text,
                },
                ensure_ascii=False,
            )
        return ToolResult.ok(output, truncated=truncated)

    def _to_markdown(self, html_content: str) -> str:
        """Convert HTML to markdown using markdownify."""
        from markdownify import markdownify

        md = markdownify(html_content, heading_style="ATX", strip=["img"])
        return _normalize(md)
