"""OpenViking tools — available when viking is enabled in config."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.viking import VikingContextProvider


class VikingSearchTool(Tool):
    """Semantic search across OpenViking resources, memories, and skills."""

    def __init__(self, provider: VikingContextProvider) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "viking_search"

    @property
    def description(self) -> str:
        return (
            "Search the OpenViking context database for relevant information. "
            "Uses semantic retrieval to find matching resources, memories, and skills. "
            "Use this to find context before answering questions or performing tasks."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query describing what information you need.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5).",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, limit: int = 5, **kwargs: Any) -> str:
        return await self._provider.search_context(query=query, limit=limit)


class VikingAddResourceTool(Tool):
    """Add a file or URL as a resource to the OpenViking context database."""

    def __init__(self, provider: VikingContextProvider) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "viking_add_resource"

    @property
    def description(self) -> str:
        return (
            "Add a file path or URL as a resource to OpenViking. "
            "The resource will be indexed and summarized for future retrieval. "
            "Supports documents (PDF, DOCX, etc.), code repositories, and web pages."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path or URL to add as a resource.",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        return await self._provider.add_resource(path)
