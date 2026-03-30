"""GraphitiMemoryBackend — Graphiti temporal knowledge graph memory backend for nanobot."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from nanobot.agent.memory import MemoryBackend
from nanobot.agent.tools.base import Tool
from nanobot_graphiti.config import GraphitiConfig

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

logger = logging.getLogger(__name__)


def _build_driver(config: GraphitiConfig) -> Any:
    """Construct the graph DB driver for the configured backend."""
    from pathlib import Path

    if config.graph_db == "kuzu":
        from graphiti_core.driver.kuzu_driver import KuzuDriver

        db_path = str(Path(config.kuzu_path).expanduser())
        Path(db_path).mkdir(parents=True, exist_ok=True)
        return KuzuDriver(db=db_path)

    if config.graph_db == "neo4j":
        from graphiti_core.driver.neo4j_driver import Neo4jDriver

        return Neo4jDriver(
            uri=config.neo4j_uri,
            user=config.neo4j_user,
            password=config.neo4j_password,
        )

    if config.graph_db == "falkordb":
        from graphiti_core.driver.falkordb_driver import FalkorDBDriver

        return FalkorDBDriver(host=config.falkordb_host, port=config.falkordb_port)

    raise ValueError(f"Unknown graph_db: {config.graph_db!r}")


def _build_graphiti(config: GraphitiConfig, provider: "LLMProvider") -> Any:
    """Build a Graphiti client wired to nanobot's LLM provider."""
    from openai import AsyncOpenAI
    from graphiti_core import Graphiti
    from graphiti_core.llm_client.openai_client import OpenAIClient as GraphitiLLMClient
    from graphiti_core.embedder.openai import OpenAIEmbedder

    if not provider.api_base:
        raise RuntimeError(
            "nanobot-graphiti requires an OpenAI-compatible provider (api_base must be set). "
            "Anthropic's native endpoint is not supported. "
            "Use an OpenAI-compat model (openrouter, openai, etc.) for Graphiti memory."
        )

    openai_client = AsyncOpenAI(
        api_key=provider.api_key or "no-key",
        base_url=provider.api_base,
    )
    llm_client = GraphitiLLMClient(
        client=openai_client,
        model=provider.get_default_model(),
    )
    embedder = OpenAIEmbedder(
        client=openai_client,
        model=config.embedding_model,
    )
    driver = _build_driver(config)
    return Graphiti(graph_driver=driver, llm_client=llm_client, embedder=embedder)


class GraphitiMemoryBackend(MemoryBackend):
    """Graphiti temporal knowledge graph memory backend."""

    consolidates_per_turn = True

    def __init__(
        self,
        config: GraphitiConfig,
        *,
        _graphiti_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._graphiti: Any | None = None
        self._graphiti_factory = _graphiti_factory

    @classmethod
    def from_nanobot_config(cls, nanobot_config: Any) -> "GraphitiMemoryBackend":
        """Instantiate from a nanobot Config object (entry-point discovery path)."""
        return cls(GraphitiConfig._from_nanobot_config(nanobot_config))

    async def start(self, provider: "LLMProvider") -> None:
        if self._graphiti_factory is not None:
            self._graphiti = self._graphiti_factory(config=self._config, provider=provider)
        else:
            self._graphiti = _build_graphiti(self._config, provider)
        await self._graphiti.build_indices_and_constraints()

    async def stop(self) -> None:
        if self._graphiti is not None:
            await self._graphiti.close()
            self._graphiti = None

    def _get_group_id(self, session_key: str) -> str:
        if self._config.scope == "user":
            _, _, chat_id = session_key.partition(":")
            return chat_id or session_key
        return session_key

    async def consolidate(self, messages: list[dict], session_key: str) -> None:
        if not messages or self._graphiti is None:
            return
        try:
            # Lazy-import EpisodeType to avoid hard dependency at module load time
            try:
                from graphiti_core.nodes import EpisodeType
                episode_source = EpisodeType.message
            except ImportError:
                # If graphiti_core is not available, use a string sentinel
                episode_source = "message"

            lines = []
            for msg in messages:
                role = msg.get("role", "unknown").capitalize()
                content = msg.get("content") or ""
                if isinstance(content, list):
                    # Handle multi-part content blocks (e.g. tool results)
                    content = " ".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in content
                    )
                if content:
                    lines.append(f"{role}: {content}")

            episode_body = "\n".join(lines)
            if not episode_body.strip():
                return

            group_id = self._get_group_id(session_key)
            await self._graphiti.add_episode(
                name=session_key,
                episode_body=episode_body,
                source_description="nanobot conversation",
                reference_time=datetime.now(timezone.utc),
                source=episode_source,
                group_id=group_id,
            )
        except Exception:
            logger.exception("GraphitiMemoryBackend.consolidate() failed — memory not updated")

    async def retrieve(self, query: str, session_key: str, top_k: int = 5) -> str:
        if self._graphiti is None:
            return ""
        try:
            group_id = self._get_group_id(session_key)
            results = await self._graphiti.search(query, group_ids=[group_id], num_results=top_k)
            if not results:
                return ""
            lines = [f"[Memory — {len(results)} relevant facts]"]
            for edge in results:
                lines.append(f"• {edge.fact}")
            return "\n".join(lines)
        except Exception:
            logger.exception("GraphitiMemoryBackend.retrieve() failed — no memory injected")
            return ""

    def get_tools(self) -> list[Tool]:
        return []  # implemented in Task 7
