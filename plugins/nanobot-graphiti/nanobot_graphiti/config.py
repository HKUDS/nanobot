"""GraphitiConfig — configuration for the nanobot-graphiti memory backend."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class GraphitiConfig(BaseModel):
    """Configuration for the Graphiti memory backend."""

    graph_db: Literal["kuzu", "neo4j", "falkordb"] = "kuzu"
    kuzu_path: str = "~/.nanobot/workspace/memory/graph"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    top_k: int = 5
    scope: Literal["user", "session"] = "user"
    embedding_model: str = "text-embedding-3-small"

    @classmethod
    def _from_nanobot_config(cls, config: Any) -> "GraphitiConfig":
        """Extract and validate Graphiti config from nanobot's Config object."""
        raw: Any = getattr(config.memory, "model_extra", {}).get("graphiti") or {}
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        return cls(**(raw if isinstance(raw, dict) else {}))
