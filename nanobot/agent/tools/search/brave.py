"""BRAVE Search Tool Implementation"""

import os
from typing import Any
import httpx
from nanobot.agent.tools.search.base import BaseSearchTool
from nanobot.config.schema import WebSearchConfig

class BraveSearchTool(BaseSearchTool):
    """Wrapper around Brave's web search API.

    This class migrated from the original :mod:`nanobot.agent.tools.web` module
    and provides a minimal interface used by :class:`WebSearchTool`.
    """

    def __init__(self, config: WebSearchConfig):
        # initialize base attributes and apply provider-specific defaults
        self.name = "brave"
        self.envName = "BRAVE_API_KEY"
        super().__init__(config)
        self.url_base = (
            self.url_base or "https://api.search.brave.com/res/v1/web/search"
        )

    def headers(self) -> dict[str, str]:
        """Return headers required by Brave (subscription token)."""
        return {"Accept": "application/json", "X-Subscription-Token": self.api_key}

    def body(self, query: str, count: int | None = None) -> dict[str, Any]:
        """Construct query parameters for the Brave search endpoint."""
        return {"q": query, "count": self.top_k(count)}

    async def request(
        self, client: httpx.AsyncClient, headers: dict, body: dict
    ) -> list:
        """HTTP GET to the Brave endpoint, returning a list of results.

        The JSON response contains a ``web`` key with ``results``; the method
        extracts and returns that list, defaulting to an empty list on
        unexpected payloads.
        """
        r = await client.get(
            self.url_base,
            params=body,
            headers=headers,
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json().get("web", {}).get("results", [])

            

        
        


