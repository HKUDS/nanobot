"""Memory tool for CRUD operations on memory collections."""

from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.base import Tool


class MemoryTool(Tool):
    """Tool for managing memory collections (brand guides, briefs, projects, user memory)."""

    def __init__(self, memory_store: MemoryStore):
        self._memory = memory_store
        self._user_id = ""

    def set_user(self, user_id: str) -> None:
        """Set the current user ID for user-scoped operations."""
        self._user_id = user_id

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return """Manage memory collections. Collections: brand_guides, briefs, projects (global/shared), users (per-user).
Actions: read, write, list, delete, search."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "list", "delete", "search", "list_collections"],
                    "description": "Action to perform",
                },
                "collection": {
                    "type": "string",
                    "enum": ["brand_guides", "briefs", "projects", "users"],
                    "description": "Memory collection (brand_guides, briefs, projects, users)",
                },
                "name": {
                    "type": "string",
                    "description": "Name of the memory item (without .md extension)",
                },
                "content": {"type": "string", "description": "Content to write (for write action)"},
                "query": {"type": "string", "description": "Search query (for search action)"},
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        collection: str | None = None,
        name: str | None = None,
        content: str | None = None,
        query: str | None = None,
        **kwargs: Any,
    ) -> str:
        if action == "list_collections":
            return self._list_collections()
        elif action == "list":
            return self._list(collection)
        elif action == "read":
            return self._read(collection, name)
        elif action == "write":
            return self._write(collection, name, content)
        elif action == "delete":
            return self._delete(collection, name)
        elif action == "search":
            return self._search(query, collection)
        return f"Unknown action: {action}"

    def _list_collections(self) -> str:
        """List available collections."""
        collections = self._memory.list_collections()
        return "Available collections:\n- " + "\n- ".join(collections)

    def _list(self, collection: str | None) -> str:
        """List items in a collection."""
        if not collection:
            return "Error: collection is required for list action"

        items = self._memory.list_items(collection, self._user_id or None)
        if not items:
            return f"No items in collection '{collection}'"

        lines = [f"Items in {collection}:"]
        for item in items:
            lines.append(f"- {item['name']} ({item['type']}, modified: {item['modified']})")

        return "\n".join(lines)

    def _read(self, collection: str | None, name: str | None) -> str:
        """Read from a memory collection."""
        if not collection or not name:
            return "Error: collection and name are required for read action"

        content = self._memory.read(collection, name, self._user_id or None)
        if not content:
            return f"No content found for '{name}' in collection '{collection}'"

        return content

    def _write(self, collection: str | None, name: str | None, content: str | None) -> str:
        """Write to a memory collection."""
        if not collection or not name:
            return "Error: collection, name, and content are required for write action"

        if content is None:
            return "Error: content is required for write action"

        user_id = self._user_id if collection == "users" else None
        result = self._memory.write(collection, name, content, user_id)
        return result

    def _delete(self, collection: str | None, name: str | None) -> str:
        """Delete from a memory collection."""
        if not collection or not name:
            return "Error: collection and name are required for delete action"

        user_id = self._user_id if collection == "users" else None
        if self._memory.delete(collection, name, user_id):
            return f"Deleted '{name}' from collection '{collection}'"
        return f"Item '{name}' not found in collection '{collection}'"

    def _search(self, query: str | None, collection: str | None) -> str:
        """Search across memory collections."""
        if not query:
            return "Error: query is required for search action"

        results = []

        if collection:
            collections = [collection]
        else:
            collections = self._memory.COLLECTIONS + (["users"] if self._user_id else [])

        for coll in collections:
            items = self._memory.list_items(coll, self._user_id or None)
            for item in items:
                content = self._memory.read(coll, item["name"], self._user_id or None)
                if query.lower() in content.lower():
                    results.append(f"## {coll}/{item['name']}\n{content[:500]}...")

        if not results:
            return f"No results found for '{query}'"

        return "\n\n---\n\n".join(results[:5])
