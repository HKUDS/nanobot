"""Web tools: web_search and web_fetch."""

import html
import ipaddress
import json
import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks

# SSRF Protection: Blocked IP ranges (private/internal networks)
BLOCKED_IP_RANGES = [
    ipaddress.ip_network('127.0.0.0/8'),      # Localhost
    ipaddress.ip_network('10.0.0.0/8'),       # Private Class A
    ipaddress.ip_network('172.16.0.0/12'),    # Private Class B
    ipaddress.ip_network('192.168.0.0/16'),   # Private Class C
    ipaddress.ip_network('169.254.0.0/16'),   # Link-local (AWS/Azure metadata!)
    ipaddress.ip_network('100.64.0.0/10'),    # Carrier-grade NAT
    ipaddress.ip_network('192.0.0.0/24'),     # IETF Protocol Assignments
    ipaddress.ip_network('192.0.2.0/24'),     # TEST-NET-1
    ipaddress.ip_network('198.51.100.0/24'),  # TEST-NET-2
    ipaddress.ip_network('203.0.113.0/24'),   # TEST-NET-3
    ipaddress.ip_network('224.0.0.0/4'),      # Multicast
    ipaddress.ip_network('240.0.0.0/4'),      # Reserved
    ipaddress.ip_network('0.0.0.0/8'),        # "This" network
    ipaddress.ip_network('::1/128'),          # IPv6 localhost
    ipaddress.ip_network('fc00::/7'),         # IPv6 private (ULA)
    ipaddress.ip_network('fe80::/10'),        # IPv6 link-local
    ipaddress.ip_network('ff00::/8'),         # IPv6 multicast
    ipaddress.ip_network('::ffff:0:0/96'),    # IPv4-mapped IPv6
]

# SSRF Protection: Blocked hostnames (cloud metadata endpoints, etc.)
BLOCKED_HOSTNAMES = {
    'localhost',
    'localhost.localdomain',
    '127.0.0.1',
    '0.0.0.0',
    '::1',
    '[::1]',
    'metadata.google.internal',       # GCP metadata
    'metadata.goog',                  # GCP metadata alternate
    '169.254.169.254',               # AWS/Azure/GCP metadata IP
    'metadata.azure.com',            # Azure metadata
    'metadata.internal',             # Generic metadata
    'kubernetes.default.svc',        # Kubernetes API
    'kubernetes.default',            # Kubernetes API
}

# SSRF Protection: Allowed protocols
ALLOWED_PROTOCOLS = {'http', 'https'}


class SSRFError(Exception):
    """Exception raised when SSRF attempt is detected."""
    pass


def _is_ip_blocked(ip_str: str) -> tuple[bool, str]:
    """Check if an IP address falls within blocked ranges.

    Args:
        ip_str: IP address as string

    Returns:
        Tuple of (is_blocked, reason)
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        for blocked_range in BLOCKED_IP_RANGES:
            if ip in blocked_range:
                return True, f"IP {ip} is in blocked range {blocked_range}"
        return False, ""
    except ValueError as e:
        return True, f"Invalid IP address: {e}"


def _validate_url_ssrf(url: str) -> str:
    """Validate URL is safe to fetch (SSRF protection).

    Performs comprehensive validation including:
    - Protocol whitelist (http/https only)
    - Hostname blocklist (cloud metadata endpoints, etc.)
    - IP range blocklist (private networks, localhost, link-local)
    - DNS resolution to catch hostname-based bypasses

    Args:
        url: The URL to validate

    Returns:
        The validated URL if safe

    Raises:
        SSRFError: If the URL is not safe to fetch
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SSRFError(f"Failed to parse URL: {e}")

    # Check protocol whitelist
    scheme = parsed.scheme.lower() if parsed.scheme else ''
    if scheme not in ALLOWED_PROTOCOLS:
        raise SSRFError(f"Protocol not allowed: '{scheme or 'none'}'. Only http/https permitted.")

    # Check for valid hostname
    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("No hostname in URL")

    # Normalize hostname for comparison
    hostname_lower = hostname.lower().strip('[]')  # Strip IPv6 brackets

    # Check hostname blocklist
    if hostname_lower in BLOCKED_HOSTNAMES:
        raise SSRFError(f"Hostname blocked: {hostname}")

    # Check for hostname patterns that might be bypass attempts
    if hostname_lower.endswith('.internal') or hostname_lower.endswith('.local'):
        raise SSRFError(f"Internal/local hostname blocked: {hostname}")

    # Check if hostname is a raw IP address
    try:
        # Try to parse as IPv4 or IPv6
        ip = ipaddress.ip_address(hostname_lower)
        is_blocked, reason = _is_ip_blocked(str(ip))
        if is_blocked:
            raise SSRFError(f"Access blocked: {reason}")
    except ValueError:
        # Not an IP address, need to resolve hostname
        pass

    # Resolve hostname to IP and check
    try:
        # Get all IP addresses for the hostname
        addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if scheme == 'https' else 80))

        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            is_blocked, reason = _is_ip_blocked(ip_str)
            if is_blocked:
                raise SSRFError(f"Resolved IP blocked: {reason}")

    except socket.gaierror as e:
        raise SSRFError(f"Cannot resolve hostname '{hostname}': {e}")
    except socket.herror as e:
        raise SSRFError(f"Host resolution error for '{hostname}': {e}")

    return url


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
    """Validate URL: must be http(s) with valid domain and pass SSRF checks.

    This function combines basic URL validation with comprehensive SSRF protection.

    Args:
        url: The URL to validate

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    try:
        # First do basic parsing check
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"

        # Then perform comprehensive SSRF validation
        _validate_url_ssrf(url)
        return True, ""
    except SSRFError as e:
        return False, f"SSRF protection: {e}"
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
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self.max_results = max_results
    
    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            return "Error: BRAVE_API_KEY not configured"
        
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
