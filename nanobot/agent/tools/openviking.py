"""OpenViking tools: read, list, search, grep, glob, memory search, memory commit."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from nanobot.agent.tools.base import Tool

try:
    from nanobot.openviking.client import VikingClient

    HAS_OPENVIKING = True
except Exception:
    HAS_OPENVIKING = False
    VikingClient = None  # type: ignore[assignment,misc]


class _OVTool(Tool):
    """Base for OpenViking tools — lazily creates a shared VikingClient."""

    _shared_client: VikingClient | None = None

    def __init__(self, ov_config: Any = None):
        self._ov_config = ov_config

    async def _client(self) -> VikingClient:
        if _OVTool._shared_client is None:
            _OVTool._shared_client = await VikingClient.from_config()
        return _OVTool._shared_client

    @classmethod
    def reset_client(cls) -> None:
        if cls._shared_client is not None:
            cls._shared_client.close()
            cls._shared_client = None


class OVReadTool(_OVTool):
    @property
    def name(self) -> str:
        return "openviking_read"

    @property
    def description(self) -> str:
        return "Read content from memory resources at different levels (abstract, overview, or full content)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "uri": {
                    "type": "string",
                    "description": "The Viking URI to read (e.g. viking://resources/path/file.md)",
                },
                "level": {
                    "type": "string",
                    "description": "Reading level: 'abstract' (~100 tokens), 'overview' (~2000 tokens), or 'read' (full)",
                    "enum": ["abstract", "overview", "read"],
                },
            },
            "required": ["uri"],
        }

    async def execute(self, uri: str, level: str = "abstract", **kwargs: Any) -> str:
        try:
            client = await self._client()
            return await client.read_content(uri, level=level) or "(empty)"
        except Exception as e:
            return f"Error reading resource: {e}"


class OVListTool(_OVTool):
    @property
    def name(self) -> str:
        return "openviking_list"

    @property
    def description(self) -> str:
        return "List resources in a memory path."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "uri": {
                    "type": "string",
                    "description": "The Viking URI to list (e.g. viking://resources/)",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list recursively",
                },
            },
            "required": ["uri"],
        }

    async def execute(self, uri: str, recursive: bool = False, **kwargs: Any) -> str:
        try:
            client = await self._client()
            entries = await client.list_resources(path=uri, recursive=recursive)
            if not entries:
                return f"No resources found at {uri}"
            lines = []
            for entry in entries:
                lines.append(
                    f"name={entry['name']}  size={entry['size']}  uri={entry['uri']}  isDir={entry['isDir']}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Error listing resources: {e}"


class OVSearchTool(_OVTool):
    @property
    def name(self) -> str:
        return "openviking_search"

    @property
    def description(self) -> str:
        return "Semantic search for resources in the memory system."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "target_uri": {
                    "type": "string",
                    "description": "Optional URI scope (e.g. viking://resources/). Omit to search everything.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, target_uri: Optional[str] = None, **kwargs: Any) -> str:
        try:
            client = await self._client()
            results = await client.search(query, target_uri=target_uri or "")
            if not results:
                return f"No results for: {query}"
            return str(results)
        except Exception as e:
            return f"Error searching memory: {e}"


class OVGrepTool(_OVTool):
    @property
    def name(self) -> str:
        return "openviking_grep"

    @property
    def description(self) -> str:
        return "Search memory resources using regex patterns."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "uri": {
                    "type": "string",
                    "description": "The Viking URI to search within",
                },
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case-insensitive search",
                },
            },
            "required": ["uri", "pattern"],
        }

    async def execute(
        self, uri: str, pattern: str, case_insensitive: bool = False, **kwargs: Any
    ) -> str:
        try:
            client = await self._client()
            result = await client.grep(uri, pattern, case_insensitive=case_insensitive)
            if isinstance(result, dict):
                payload = result.get("result", result)
                matches = payload.get("matches", [])
                count = payload.get("count", 0)
            else:
                matches = getattr(result, "matches", [])
                count = getattr(result, "count", 0)

            if not matches:
                return f"No matches for pattern: {pattern}"

            lines = [f"Found {count} match{'es' if count != 1 else ''}:"]
            for m in matches:
                m_uri = m.get("uri", "") if isinstance(m, dict) else getattr(m, "uri", "")
                line = m.get("line", "?") if isinstance(m, dict) else getattr(m, "line", "?")
                content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                lines.append(f"  {m_uri}:{line} {content}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error in openviking_grep: {e}"


class OVGlobTool(_OVTool):
    @property
    def name(self) -> str:
        return "openviking_glob"

    @property
    def description(self) -> str:
        return "Find memory resources using glob patterns (e.g. **/*.md)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. **/*.md, *.py)",
                },
                "uri": {
                    "type": "string",
                    "description": "Base Viking URI to search within",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, uri: str = "", **kwargs: Any) -> str:
        try:
            client = await self._client()
            result = await client.glob(pattern, uri=uri or "viking://")
            if isinstance(result, dict):
                payload = result.get("result", result)
                matches = payload.get("matches", [])
                count = payload.get("count", 0)
            else:
                matches = getattr(result, "matches", [])
                count = getattr(result, "count", 0)

            if not matches:
                return f"No files for pattern: {pattern}"

            lines = [f"Found {count} file{'s' if count != 1 else ''}:"]
            for m in matches:
                m_uri = m.get("uri", str(m)) if isinstance(m, dict) else str(m)
                lines.append(f"  {m_uri}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error in openviking_glob: {e}"


class OVUserMemorySearchTool(_OVTool):
    @property
    def name(self) -> str:
        return "user_memory_search"

    @property
    def description(self) -> str:
        return "Search user memories for past conversations and preferences."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "sender_id": {
                    "type": "string",
                    "description": "Optional user ID to scope memory search. Defaults to the configured user.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, sender_id: str = "", **kwargs: Any) -> str:
        try:
            client = await self._client()
            results = await client.search_user_memory(query, sender_id=sender_id)
            if not results:
                return f"No user memories found for: {query}"
            return str(results)
        except Exception as e:
            return f"Error searching user memories: {e}"


class OVMemoryCommitTool(_OVTool):
    """Commit messages to OpenViking session for persistent memory."""

    _pending_tasks: set[asyncio.Task[Any]] = set()

    def __init__(
        self,
        ov_config: Any = None,
        session_key_fn: Any = None,
        background_task_scheduler: Any = None,
    ):
        super().__init__(ov_config)
        self._session_key_fn = session_key_fn
        self._background_task_scheduler = background_task_scheduler

    @property
    def name(self) -> str:
        return "openviking_memory_commit"

    @property
    def description(self) -> str:
        return "Commit conversation messages for persistent memory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "description": "Messages to commit",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["user", "assistant"]},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                },
                "sender_id": {
                    "type": "string",
                    "description": "Optional user ID for per-user memory isolation.",
                },
            },
            "required": ["messages"],
        }

    async def execute(self, messages: list[dict[str, Any]], sender_id: str = "", **kwargs: Any) -> str:
        try:
            client = await self._client()
            session_id = self._session_key_fn() if self._session_key_fn else "default"
            commit_coro = self._commit_in_background(
                client=client,
                session_id=session_id,
                messages=messages,
                sender_id=sender_id,
            )
            if self._background_task_scheduler is not None:
                self._background_task_scheduler(commit_coro)
            else:
                task = asyncio.create_task(commit_coro)
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard)
            return (
                f"Queued background memory commit for {len(messages)} messages "
                f"(session={session_id})."
            )
        except Exception as e:
            logger.exception("Error committing to memory")
            return f"Error committing to memory: {e}"

    @staticmethod
    async def _commit_in_background(
        *,
        client: VikingClient,
        session_id: str,
        messages: list[dict[str, Any]],
        sender_id: str,
    ) -> None:
        try:
            result = await client.commit(session_id, messages, sender_id=sender_id)
            if not result.get("success"):
                logger.warning(
                    "OpenViking background commit reported failure for session {}: {}",
                    session_id,
                    result,
                )
        except Exception:
            logger.exception(
                "OpenViking background commit failed for session {}", session_id
            )


class OVAddResourceTool(_OVTool):
    @property
    def name(self) -> str:
        return "openviking_add_resource"

    @property
    def description(self) -> str:
        return "Add a local file as a resource for semantic indexing."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "description": "Path to the local file"},
                "description": {"type": "string", "description": "Description of the resource"},
                "target_path": {
                    "type": "string",
                    "description": "Optional target path in the memory system to store the resource",
                },
                "wait": {
                    "type": "boolean",
                    "description": "Whether to wait for processing to complete",
                },
            },
            "required": ["local_path", "description"],
        }

    async def execute(
        self, local_path: str, description: str, target_path: str = "", wait: bool = False, **kwargs: Any
    ) -> str:
        try:
            path = Path(local_path).expanduser().resolve()
            if not path.exists():
                return f"Error: File not found: {local_path}"
            if not path.is_file():
                return f"Error: Not a file: {local_path}"

            client = await self._client()
            result = await client.add_resource(str(path), description, target_path=target_path, wait=wait)
            if result:
                payload = result.get("result", result)
                root_uri = payload.get("root_uri", "unknown")
                content_uri = payload.get("content_uri", root_uri)
                if content_uri != root_uri:
                    return f"Successfully added resource: root={root_uri} content={content_uri}"
                return f"Successfully added resource: {root_uri}"
            return "Failed to add resource"
        except Exception as e:
            return f"Error adding resource: {e}"


ALL_OV_TOOLS = [
    OVReadTool,
    OVListTool,
    OVSearchTool,
    OVGrepTool,
    OVGlobTool,
    OVUserMemorySearchTool,
    OVMemoryCommitTool,
    OVAddResourceTool,
]
