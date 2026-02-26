"""Baidu Search Tool Implementation"""

import os
from typing import Any
import httpx
from nanobot.agent.tools.search.base import BaseSearchTool
from nanobot.config.schema import WebSearchConfig

class BaiduSearchTool(BaseSearchTool):
    """Adapter for querying the Baidu web search API.

    This tool wraps the Qianfan/Baidu "ai_search" endpoint and normalizes the
    response into a simple list of result dictionaries.  The configuration is
    provided via :class:`~nanobot.config.schema.WebSearchConfig` and the API key
    may also be supplied through the ``BAIDU_API_KEY`` environment variable.
    """

    def __init__(self, config: WebSearchConfig):
        # initialise parent and apply defaults
        self.name = "baidu"
        self.envName = "BAIDU_API_KEY"
        self.limit_results = 50
        super().__init__(config)
        self.url_base = (
            self.url_base
            or "https://qianfan.baidubce.com/v2/ai_search/web_search"
        )

    def headers(self) -> dict[str, str]:
        """Return the default HTTP headers required by the API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def body(self, query: str, count: int | None = None, **kwargs: Any) -> dict[str, Any]:
        """Construct the JSON payload for a search request.

        :param query: text to search for
        :param count: desired maximum number of results; falls back to the
            configured ``max_results`` and is limited by ``limit_results``.
        :param kwargs: ignored for now but allows flexibility for future
            parameters like ``edition`` or ``search_filter``.
        :return: dictionary ready to be serialized as JSON
        """

        top_k = self.top_k(count)
        return {
            "messages": [{"content": query, "role": "user"}],
            "edition": "standard",
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": top_k}],
        }

    async def request(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Perform the HTTP POST and normalise the response.

        Raises an exception if the remote service returns an error code.
        """

        response = await client.post(
            self.url_base,
            json=body,
            headers=headers,
            timeout=10.0,
        )
        response.raise_for_status()

        results = response.json()
        if "code" in results:
            # the API returns a code/message pair when something went wrong
            raise Exception(f'{results["code"]}: {results.get("message")}')

        references = results.get("references", [])
        normalized: list[dict[str, str]] = []
        for item in references:
            normalized.append(
                {
                    "icon": item.get("icon", ""),
                    "date": item.get("date", ""),
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("content", ""),
                }
            )
        return normalized


        
        


