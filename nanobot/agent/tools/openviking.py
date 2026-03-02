"""OpenViking tools: persistent memory and semantic search for agents."""
from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool


class OVBaseTool(Tool):
    """Base class for all OpenViking tools."""

    def __init__(self, data_path: str) -> None:
        self._data_path = data_path
        self._channel: str = ""
        self._chat_id: str = ""

    def set_context(self, channel: str, chat_id: str) -> None:
        self._channel = channel
        self._chat_id = chat_id

    @property
    def _session_key(self) -> str:
        return f"{self._channel}:{self._chat_id}"

    async def _get_client(self):
        from nanobot.agent.tools.openviking_client import get_client
        return await get_client(self._data_path)


class OpenVikingReadTool(OVBaseTool):
    name = "openviking_read"
    description = (
        "Read content from the OpenViking memory store at a given URI. "
        "Use viking:// URIs returned by openviking_search or openviking_list."
    )
    parameters = {
        "type": "object",
        "properties": {
            "uri": {"type": "string", "description": "Viking URI to read (e.g. viking://memory/...)"},
        },
        "required": ["uri"],
    }

    async def execute(self, uri: str, **kwargs: Any) -> str:
        client = await self._get_client()
        return await client.read(uri)


class OpenVikingListTool(OVBaseTool):
    name = "openviking_list"
    description = "List resources in the OpenViking memory store at a given URI."
    parameters = {
        "type": "object",
        "properties": {
            "uri": {"type": "string", "description": "Viking URI to list"},
            "recursive": {"type": "boolean", "description": "List recursively", "default": False},
        },
        "required": ["uri"],
    }

    async def execute(self, uri: str, recursive: bool = False, **kwargs: Any) -> str:
        client = await self._get_client()
        result = await client.ls(uri, recursive=recursive)
        return json.dumps(result, ensure_ascii=False, indent=2)


class OpenVikingSearchTool(OVBaseTool):
    name = "openviking_search"
    description = "Semantic search over the OpenViking memory store."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural language search query"},
            "uri": {
                "type": "string",
                "description": "Scope URI to search within (default: viking://)",
                "default": "viking://",
            },
            "limit": {"type": "integer", "description": "Maximum number of results", "default": 10},
        },
        "required": ["query"],
    }

    async def execute(self, query: str, uri: str = "viking://", limit: int = 10, **kwargs: Any) -> str:
        client = await self._get_client()
        result = await client.search(query=query, target_uri=uri, limit=limit)
        return str(result)


class OpenVikingGrepTool(OVBaseTool):
    name = "openviking_grep"
    description = "Grep for a regex pattern in the OpenViking memory store."
    parameters = {
        "type": "object",
        "properties": {
            "uri": {"type": "string", "description": "Viking URI to search in"},
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "case_insensitive": {
                "type": "boolean",
                "description": "Case-insensitive search",
                "default": False,
            },
        },
        "required": ["uri", "pattern"],
    }

    async def execute(self, uri: str, pattern: str, case_insensitive: bool = False, **kwargs: Any) -> str:
        client = await self._get_client()
        result = await client.grep(uri=uri, pattern=pattern, case_insensitive=case_insensitive)
        return json.dumps(result, ensure_ascii=False, indent=2)


class OpenVikingGlobTool(OVBaseTool):
    name = "openviking_glob"
    description = "Glob pattern matching over the OpenViking memory store."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (e.g. viking://memory/**/*.md)"},
            "uri": {
                "type": "string",
                "description": "Base URI (default: viking://)",
                "default": "viking://",
            },
        },
        "required": ["pattern"],
    }

    async def execute(self, pattern: str, uri: str = "viking://", **kwargs: Any) -> str:
        client = await self._get_client()
        result = await client.glob(pattern=pattern, uri=uri)
        return json.dumps(result, ensure_ascii=False, indent=2)


class UserMemorySearchTool(OVBaseTool):
    name = "user_memory_search"
    description = (
        "Search user memories stored in OpenViking. "
        "Use this to recall past conversations, user preferences, and learned facts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for in user memories"},
            "limit": {"type": "integer", "description": "Maximum number of results", "default": 10},
        },
        "required": ["query"],
    }

    async def execute(self, query: str, limit: int = 10, **kwargs: Any) -> str:
        client = await self._get_client()
        result = await client.search(
            query=query,
            target_uri="viking://memory/",
            limit=limit,
        )
        return str(result)


OV_TOOLS = [
    OpenVikingReadTool,
    OpenVikingListTool,
    OpenVikingSearchTool,
    OpenVikingGrepTool,
    OpenVikingGlobTool,
    UserMemorySearchTool,
]
