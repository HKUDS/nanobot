"""Web search provider usage fetchers for /status command."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class SearchUsageInfo:
    """Structured usage info returned by a provider fetcher."""

    provider: str
    supported: bool = False          # True if the provider has a usage API
    error: str | None = None         # Set when the API call failed

    # Usage counters (None = not available for this provider)
    used: int | None = None
    limit: int | None = None
    remaining: int | None = None
    reset_date: str | None = None    # ISO date string, e.g. "2026-05-01"

    # Tavily-specific breakdown
    search_used: int | None = None
    extract_used: int | None = None
    crawl_used: int | None = None

    def format(self) -> str:
        """Return a human-readable multi-line string for /status output."""
        lines = [f"🔍 Web Search: {self.provider}"]

        if not self.supported:
            lines.append("   Usage tracking: not available for this provider")
            return "\n".join(lines)

        if self.error:
            lines.append(f"   Usage: unavailable ({self.error})")
            return "\n".join(lines)

        if self.used is not None and self.limit is not None:
            lines.append(f"   Usage: {self.used} / {self.limit} requests")
        elif self.used is not None:
            lines.append(f"   Usage: {self.used} requests")

        # Tavily breakdown
        breakdown_parts = []
        if self.search_used is not None:
            breakdown_parts.append(f"Search: {self.search_used}")
        if self.extract_used is not None:
            breakdown_parts.append(f"Extract: {self.extract_used}")
        if self.crawl_used is not None:
            breakdown_parts.append(f"Crawl: {self.crawl_used}")
        if breakdown_parts:
            lines.append(f"   Breakdown: {' | '.join(breakdown_parts)}")

        if self.remaining is not None:
            lines.append(f"   Remaining: {self.remaining} requests")

        if self.reset_date:
            lines.append(f"   Resets: {self.reset_date}")

        return "\n".join(lines)


async def fetch_search_usage(
    provider: str,
    api_key: str | None = None,
) -> SearchUsageInfo:
    """
    Fetch usage info for the configured web search provider.

    Args:
        provider: Provider name (e.g. "tavily", "brave", "duckduckgo").
        api_key:  API key for the provider (falls back to env vars).

    Returns:
        SearchUsageInfo with populated fields where available.
    """
    p = (provider or "duckduckgo").strip().lower()

    if p == "tavily":
        return await _fetch_tavily_usage(api_key)
    elif p == "brave":
        return await _fetch_brave_usage(api_key)
    else:
        # duckduckgo, searxng, jina, unknown — no usage API
        return SearchUsageInfo(provider=p, supported=False)


# ---------------------------------------------------------------------------
# Tavily
# ---------------------------------------------------------------------------

async def _fetch_tavily_usage(api_key: str | None) -> SearchUsageInfo:
    """Fetch usage from GET https://api.tavily.com/usage."""
    import httpx

    key = api_key or os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return SearchUsageInfo(
            provider="tavily",
            supported=True,
            error="TAVILY_API_KEY not configured",
        )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://api.tavily.com/usage",
                headers={"Authorization": f"Bearer {key}"},
            )
            r.raise_for_status()
        data: dict[str, Any] = r.json()
        return _parse_tavily_usage(data)
    except httpx.HTTPStatusError as e:
        return SearchUsageInfo(
            provider="tavily",
            supported=True,
            error=f"HTTP {e.response.status_code}",
        )
    except Exception as e:
        return SearchUsageInfo(
            provider="tavily",
            supported=True,
            error=str(e)[:80],
        )


def _parse_tavily_usage(data: dict[str, Any]) -> SearchUsageInfo:
    """
    Parse Tavily /usage response.

    Expected shape (may vary by plan):
    {
      "used": 142,
      "limit": 1000,
      "remaining": 858,
      "reset_date": "2026-05-01",
      "breakdown": {
        "search": 120,
        "extract": 15,
        "crawl": 7
      }
    }
    """
    used = data.get("used")
    limit = data.get("limit")
    remaining = data.get("remaining")
    reset_date = data.get("reset_date") or data.get("resetDate")

    # Compute remaining if not provided
    if remaining is None and used is not None and limit is not None:
        remaining = max(0, limit - used)

    breakdown = data.get("breakdown") or {}
    search_used = breakdown.get("search")
    extract_used = breakdown.get("extract")
    crawl_used = breakdown.get("crawl")

    return SearchUsageInfo(
        provider="tavily",
        supported=True,
        used=used,
        limit=limit,
        remaining=remaining,
        reset_date=str(reset_date) if reset_date else None,
        search_used=search_used,
        extract_used=extract_used,
        crawl_used=crawl_used,
    )


# ---------------------------------------------------------------------------
# Brave
# ---------------------------------------------------------------------------

async def _fetch_brave_usage(api_key: str | None) -> SearchUsageInfo:
    """
    Brave Search does not have a public usage/quota endpoint.
    Rate-limit headers are returned per-request, not queryable standalone.
    """
    return SearchUsageInfo(provider="brave", supported=False)
