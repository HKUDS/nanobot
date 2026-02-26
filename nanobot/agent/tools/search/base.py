"""Base interface for search tools."""

import os

import httpx

from nanobot.config.schema import WebSearchConfig
from abc import ABC, abstractmethod
from typing import Any

class BaseSearchTool(ABC):
    """Abstract interface for wrapping a web search provider.

    Concrete implementations must supply HTTP headers and request bodies
    appropriate for the remote API, and perform the actual network
    interaction in :meth:`request`.

    Attributes are populated from a :class:`~nanobot.config.schema.WebSearchConfig`
    instance passed to :meth:`__init__`.
    """

    name: str = "base"
    envName: str = "SEARCH_API_KEY"
    url_base: str | None = None
    api_key: str | None = None
    max_results: int = 5
    limit_results: int = 10

    def __init__(self, config: WebSearchConfig):
        # copy configuration values; subclasses may override or extend
        self.name = config.provider
        self.url_base = config.url_base
        self.api_key = config.api_key or os.environ.get(self.envName, "")
        self.max_results = config.max_results

    def headers(self) -> dict[str, str]:
        """Return a dictionary of HTTP headers to send with each request.

        Subclasses should override this method to inject authorization tokens
        or custom content types.  The default implementation simply returns an
        empty map.
        """
        return {}

    def body(
        self, query: str, count: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Build the JSON payload for a search call.

        :param query: user-supplied search string
        :param count: desired number of results
        :param kwargs: additional provider-specific parameters
        :return: request body ready for ``json=`` in ``httpx``
        """
        raise NotImplementedError("subclasses must implement body()")

    def top_k(self, count: int | None = None) -> int:
        """Normalize requested count to a valid range.

        Ensures the value is at least ``1`` and does not exceed
        ``self.limit_results``.  Falls back to ``self.max_results`` when
        ``count`` is ``None``.
        """
        return min(max(count or self.max_results, 1), self.limit_results)

    async def queryStringify(
        self, query: str, count: int | None = None, **kwargs: Any
    ) -> str:
        """Return a formatted string of search results.

        The output is crafted to match the format produced by
        :class:`~nanobot.agent.tools.web.WebSearchTool` 
        """
        try:
            results = await self.query(query, count, **kwargs)
        except Exception as e:  # pragma: no cover - simple formatting
            return f"Error: {type(e).__name__}, {e}"

        if not results:
            return f"No results for: {query}"

        lines: list[str] = [f"Results for: {query}\n"]
        for i, item in enumerate(results, 1):
            title = item.get("title", "")
            url = item.get("url", "")
            desc = item.get("description", "")
            lines.append(f"{i}. {title}\n   {url}")
            if desc:
                lines.append(f"   {desc}")
        return "\n".join(lines)

    async def query(
        self, query: str, count: int | None = None, **kwargs: Any
    ) -> list:
        """Execute a query against the configured provider.

        Raises an exception if the API key is missing or the network request
        fails.  Delegates header/body generation to ``headers`` and ``body``
        methods and performs the request using an ``httpx.AsyncClient`` to
        simplify usage for subclasses.
        """
        if not self.api_key:
            raise Exception(f"Error: current provider {self.name} , both config.json[tools.web.search.apiKey] and env[{self.envName}] are not configured")

        headers = self.headers()
        request_body = self.body(query, count, **kwargs)
        async with httpx.AsyncClient() as client:
            return await self.request(client, headers, request_body)

    @abstractmethod
    async def request(
        self, client: httpx.AsyncClient, headers: dict, body: dict
    ) -> list:
        """Perform the HTTP interaction and return a list of result dictionaries.

        Subclasses must implement this method; the base class does not make any
        assumptions about how the remote API behaves.
        """
        raise NotImplementedError
