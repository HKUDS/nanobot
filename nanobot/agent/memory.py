"""Memory system for persistent agent memory with user isolation and collections."""

from pathlib import Path
from datetime import datetime
from typing import Any

from nanobot.utils.helpers import ensure_dir, safe_filename


class MemoryStore:
    """
    Multi-layer memory system:

    1. Global collections: brand_guides, briefs, projects (shared across users)
    2. User memory: per-user preferences and history
    3. Legacy: MEMORY.md/HISTORY.md for backward compatibility

    Structure:
        memory/
        ├── global/
        │   ├── brand_guides/
        │   ├── briefs/
        │   └── projects/
        ├── users/
        │   └── {user_id}/
        │       ├── preferences.md
        │       └── history.md
        ├── MEMORY.md (legacy)
        └── HISTORY.md (legacy)
    """

    COLLECTIONS = ["brand_guides", "briefs", "projects"]

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_dir = ensure_dir(workspace / "memory")

        self.global_dir = ensure_dir(self.memory_dir / "global")
        self.users_dir = ensure_dir(self.memory_dir / "users")

        for coll in self.COLLECTIONS:
            ensure_dir(self.global_dir / coll)

        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def _get_user_dir(self, user_id: str) -> Path:
        """Get or create user-specific directory."""
        safe_id = safe_filename(user_id)
        return ensure_dir(self.users_dir / safe_id)

    def _get_collection_dir(self, collection: str, global_only: bool = False) -> Path:
        """Get collection directory."""
        if global_only:
            return ensure_dir(self.global_dir / collection)
        return ensure_dir(self.global_dir / collection)

    def _get_user_history_file(self, user_id: str) -> Path:
        """Get user-specific history file."""
        return self._get_user_dir(user_id) / "history.md"

    def _get_user_preferences_file(self, user_id: str) -> Path:
        """Get user-specific preferences file."""
        return self._get_user_dir(user_id) / "preferences.md"

    def list_collections(self, collection: str | None = None) -> list[str]:
        """List available memory collections or items in a collection."""
        if collection:
            coll_dir = self._get_collection_dir(collection, global_only=True)
            if coll_dir.exists():
                return [f.stem for f in coll_dir.glob("*.md")]
            return []
        return list(self.COLLECTIONS)

    def list_items(self, collection: str, user_id: str | None = None) -> list[dict[str, Any]]:
        """List items in a collection. If user_id provided, include user's memory."""
        items = []
        coll_dir = self._get_collection_dir(collection, global_only=True)

        if coll_dir.exists():
            for f in coll_dir.glob("*.md"):
                items.append(
                    {
                        "name": f.stem,
                        "path": str(f.relative_to(self.memory_dir)),
                        "type": "global",
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    }
                )

        if user_id:
            user_hist = self._get_user_history_file(user_id)
            if user_hist.exists():
                items.append(
                    {
                        "name": "history",
                        "path": str(user_hist.relative_to(self.memory_dir)),
                        "type": "user",
                        "modified": datetime.fromtimestamp(user_hist.stat().st_mtime).isoformat(),
                    }
                )

            user_pref = self._get_user_preferences_file(user_id)
            if user_pref.exists():
                items.append(
                    {
                        "name": "preferences",
                        "path": str(user_pref.relative_to(self.memory_dir)),
                        "type": "user",
                        "modified": datetime.fromtimestamp(user_pref.stat().st_mtime).isoformat(),
                    }
                )

        return items

    def read(self, collection: str, name: str, user_id: str | None = None) -> str:
        """Read content from a memory collection or user memory."""
        if user_id and collection == "users":
            if name == "history":
                path = self._get_user_history_file(user_id)
            elif name == "preferences":
                path = self._get_user_preferences_file(user_id)
            else:
                path = self._get_user_dir(user_id) / f"{name}.md"
        else:
            path = self._get_collection_dir(collection, global_only=True) / f"{name}.md"

        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def write(self, collection: str, name: str, content: str, user_id: str | None = None) -> str:
        """Write content to a memory collection or user memory."""
        if user_id and collection == "users":
            if name == "history":
                path = self._get_user_history_file(user_id)
            elif name == "preferences":
                path = self._get_user_preferences_file(user_id)
            else:
                path = self._get_user_dir(user_id) / f"{name}.md"
        else:
            path = self._get_collection_dir(collection, global_only=True) / f"{name}.md"

        path.write_text(content, encoding="utf-8")
        return f"Written to {path.relative_to(self.memory_dir)}"

    def delete(self, collection: str, name: str, user_id: str | None = None) -> bool:
        """Delete content from a memory collection or user memory."""
        if user_id and collection == "users":
            if name == "history":
                path = self._get_user_history_file(user_id)
            elif name == "preferences":
                path = self._get_user_preferences_file(user_id)
            else:
                path = self._get_user_dir(user_id) / f"{name}.md"
        else:
            path = self._get_collection_dir(collection, global_only=True) / f"{name}.md"

        if path.exists():
            path.unlink()
            return True
        return False

    def append_history(self, entry: str, user_id: str | None = None) -> None:
        """Append to global history or user-specific history."""
        if user_id:
            history_file = self._get_user_history_file(user_id)
        else:
            history_file = self.history_file

        with open(history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_user_context(self, user_id: str) -> str:
        """Get user-specific memory context for agent prompts."""
        parts = []

        user_pref = self._get_user_preferences_file(user_id)
        if user_pref.exists():
            content = user_pref.read_text(encoding="utf-8")
            if content:
                parts.append(f"## User Preferences\n{content}")

        parts.append(
            f"## User Memory Location\nUser ID: {user_id}\n- Preferences: {self._get_user_preferences_file(user_id)}\n- History: {self._get_user_history_file(user_id)}"
        )

        return "\n\n".join(parts)

    def get_global_context(self, collections: list[str] | None = None) -> str:
        """Get global memory context from specified collections."""
        if collections is None:
            collections = self.COLLECTIONS

        parts = []
        for coll in collections:
            coll_dir = self._get_collection_dir(coll, global_only=True)
            if coll_dir.exists():
                items = list(coll_dir.glob("*.md"))
                if items:
                    part = f"## {coll.replace('_', ' ').title()}\n"
                    for f in items:
                        content = f.read_text(encoding="utf-8")
                        if content:
                            part += f"\n### {f.stem}\n{content}\n"
                    parts.append(part)

        return "\n\n".join(parts) if parts else ""

    def read_long_term(self) -> str:
        """Legacy: Read from MEMORY.md."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """Legacy: Write to MEMORY.md."""
        self.memory_file.write_text(content, encoding="utf-8")

    def get_memory_context(self) -> str:
        """Legacy: Get memory context for backward compatibility."""
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""
