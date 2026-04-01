"""Graphiti memory store adapter.

Wraps the ``graphiti-core`` library to provide temporal knowledge-graph memory.
Unlike flat vector stores, Graphiti tracks *how facts change over time*: every
fact carries ``valid_at`` / ``invalid_at`` timestamps so the agent can always
query "what was true at this point?" rather than just "what matches this query?"

Key features:
- Temporal fact management with bi-temporal tracking
- Hybrid retrieval (semantic + BM25 keyword + graph traversal)
- Incremental graph construction — no batch recomputation
- Pluggable graph backends: Neo4j, FalkorDB, Kuzu

Install::

    pip install graphiti-core               # Neo4j backend
    pip install "graphiti-core[falkordb]"   # FalkorDB backend (simpler setup)
    pip install "graphiti-core[kuzu]"       # Kuzu backend (embedded, no server)

Reference: https://github.com/getzep/graphiti
"""

from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.memory.base import BaseMemoryStore

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


# ── helpers ──────────────────────────────────────────────────────────────────

def _camel_to_snake(name: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s).lower()


def _normalize_keys(d: dict) -> dict:
    """Recursively convert camelCase dict keys to snake_case."""
    if not isinstance(d, dict):
        return d
    return {_camel_to_snake(k): _normalize_keys(v) for k, v in d.items()}


# ── lazy imports ──────────────────────────────────────────────────────────────

def _lazy_import_graphiti():
    try:
        from graphiti_core import Graphiti
        return Graphiti
    except ImportError:
        raise ImportError(
            "graphiti-core is required for GraphitiMemoryStore.\n"
            "  pip install graphiti-core              # Neo4j backend\n"
            "  pip install 'graphiti-core[falkordb]'  # FalkorDB backend\n"
            "  pip install 'graphiti-core[kuzu]'      # Kuzu backend"
        )


# ── client builders ──────────────────────────────────────────────────────────

def _build_async_openai(cfg: dict[str, Any]):
    """Create an ``AsyncOpenAI`` client from a normalised config dict."""
    from openai import AsyncOpenAI
    return AsyncOpenAI(
        api_key=cfg.get("api_key"),
        base_url=cfg.get("base_url"),
    )


def _build_llm_client(llm_cfg: dict[str, Any]):
    """Build a Graphiti LLM client using ``AzureOpenAILLMClient``.

    Despite the "Azure" name, this client accepts any ``AsyncOpenAI`` instance
    and uses ``beta.chat.completions.parse`` for structured output — this avoids
    all JSON-format compatibility issues with proxy APIs.
    """
    from graphiti_core.llm_client.azure_openai_client import AzureOpenAILLMClient
    from graphiti_core.llm_client.config import LLMConfig

    cfg = _normalize_keys(llm_cfg)
    client = _build_async_openai(cfg)

    class _FixedAzureOpenAILLMClient(AzureOpenAILLMClient):
        """Patch for return-value mismatch in ``AzureOpenAILLMClient``.

        The base class's ``generate_response`` unpacks the result of
        ``_generate_response`` as ``(response, input_tokens, output_tokens)``,
        but ``AzureOpenAILLMClient._handle_structured_response`` may return a
        plain dict.  We normalise the return value to always be a 3-tuple.
        """

        async def _generate_response(self, *args, **kwargs):
            result = await super()._generate_response(*args, **kwargs)
            if not isinstance(result, tuple):
                return result, 0, 0
            if len(result) == 1:
                return result[0], 0, 0
            return result

        def _handle_structured_response(self, *args, **kwargs):
            result = super()._handle_structured_response(*args, **kwargs)
            if not isinstance(result, tuple):
                return result, 0, 0
            if len(result) == 1:
                return result[0], 0, 0
            return result

    config = LLMConfig(
        model=cfg.get("model"),
        small_model=cfg.get("small_model", cfg.get("model")),
    )
    return _FixedAzureOpenAILLMClient(azure_client=client, config=config)


def _build_embedder(embedder_cfg: dict[str, Any]):
    """Build a Graphiti embedder using ``AzureOpenAIEmbedderClient``."""
    from graphiti_core.embedder.azure_openai import AzureOpenAIEmbedderClient

    cfg = _normalize_keys(embedder_cfg)
    client = _build_async_openai(cfg)
    model = cfg.get("model") or cfg.get("embedding_model") or "text-embedding-3-small"
    return AzureOpenAIEmbedderClient(azure_client=client, model=model)


def _build_cross_encoder(cross_encoder_cfg: dict[str, Any]):
    """Build a Graphiti cross-encoder (reranker) using ``OpenAIRerankerClient``."""
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.llm_client.config import LLMConfig

    cfg = _normalize_keys(cross_encoder_cfg)
    client = _build_async_openai(cfg)
    config = LLMConfig(
        model=cfg.get("model"),
        small_model=cfg.get("small_model", cfg.get("model")),
    )
    return OpenAIRerankerClient(client=client, config=config)


# ── graph DB resolver ────────────────────────────────────────────────────────

def _resolve_graph_db(graph_db_cfg: dict[str, Any], workspace: Path):
    """Parse the ``graph_db`` nested config dict and return Graphiti constructor kwargs.

    The config is a dict whose keys are backend names.  Exactly one should have
    ``"enable": true``.  Example::

        "graph_db": {
            "neo4j": {
                "enable": true,
                "url": "bolt://localhost:7687",
                "user": "neo4j",
                "database": "neo4j",
                "password": "rag-core"
            }
        }

    Supported backends: ``neo4j``, ``falkordb``, ``kuzu``.
    """
    cfg = _normalize_keys(graph_db_cfg)

    enabled_db: str | None = None
    enabled_cfg: dict[str, Any] = {}
    for db_name, db_conf in cfg.items():
        if not isinstance(db_conf, dict):
            continue
        if db_conf.get("enable", db_conf.get("enabled", False)):
            if enabled_db is not None:
                raise ValueError(
                    f"Multiple graph_db backends enabled: '{enabled_db}' and '{db_name}'. "
                    "Only one may be enabled at a time."
                )
            enabled_db = db_name
            enabled_cfg = db_conf

    if enabled_db is None:
        logger.warning("No graph_db backend enabled in config, defaulting to Neo4j localhost")
        return {"uri": "bolt://localhost:7687", "user": "neo4j", "password": "password"}

    db_type = enabled_db.lower()

    if db_type == "neo4j":
        uri = enabled_cfg.get("url") or enabled_cfg.get("uri", "bolt://localhost:7687")
        kwargs: dict[str, Any] = {
            "uri": uri,
            "user": enabled_cfg.get("user", "neo4j"),
            "password": enabled_cfg.get("password", "password"),
        }
        database = enabled_cfg.get("database")
        if database:
            from graphiti_core.driver.neo4j_driver import Neo4jDriver
            kwargs = {
                "graph_driver": Neo4jDriver(
                    uri=uri,
                    user=enabled_cfg.get("user", "neo4j"),
                    password=enabled_cfg.get("password", "password"),
                    database=database,
                )
            }
        return kwargs

    if db_type == "falkordb":
        from graphiti_core.driver.falkordb_driver import FalkorDriver
        driver = FalkorDriver(
            host=enabled_cfg.get("host", "localhost"),
            port=int(enabled_cfg.get("port", 6379)),
            username=enabled_cfg.get("username") or enabled_cfg.get("user"),
            password=enabled_cfg.get("password"),
            database=enabled_cfg.get("database", "default_db"),
        )
        return {"graph_driver": driver}

    if db_type == "kuzu":
        from graphiti_core.driver.kuzu_driver import KuzuDriver
        db_path = enabled_cfg.get("db_path") or str(workspace / "graphiti_kuzu")
        return {"graph_driver": KuzuDriver(db=db_path)}

    raise ValueError(
        f"Unknown graph_db backend '{enabled_db}'. Supported: 'neo4j', 'falkordb', 'kuzu'."
    )


# ── store ─────────────────────────────────────────────────────────────────────

class GraphitiMemoryStore(BaseMemoryStore):
    """Memory store backed by Graphiti — a temporal context graph engine.

    Configuration (in ``~/.nanobot/config.json``)::

        "graphiti": {
            "enabled": true,

            "graph_db": {
                "neo4j": {
                    "enable": true,
                    "url": "bolt://localhost:7687",
                    "user": "neo4j",
                    "database": "neo4j",
                    "password": "rag-core"
                },
                "falkordb": { "enable": false, "host": "localhost", "port": 6379 },
                "kuzu": { "enable": true, "dbPath": "./graphiti_kuzu" }
            },

            "llm": {
                "model": "gpt-4o-mini",
                "apiKey": "sk-...",
                "baseUrl": "https://..."
            },

            "embedder": {
                "model": "text-embedding-3-small",
                "apiKey": "sk-...",
                "baseUrl": "https://..."
            },

            "crossEncoder": {
                "model": "gpt-4.1-nano",
                "apiKey": "sk-...",
                "baseUrl": "https://..."
            }
        }
    """

    def __init__(
        self,
        workspace: Path,
        *,
        graph_db: dict[str, Any] | None = None,
        llm: dict[str, Any] | None = None,
        embedder: dict[str, Any] | None = None,
        cross_encoder: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        super().__init__(workspace)
        self._graph_db_cfg = graph_db
        self._llm_cfg = llm
        self._embedder_cfg = embedder
        self._cross_encoder_cfg = cross_encoder
        self._graphiti: Any = None
        self._initialized = False

        # Persistent event loop for ALL Graphiti async operations.
        # FalkorDB/Neo4j bind connection pools to the loop at construction
        # time, so using a single dedicated loop avoids "Future attached to
        # a different loop" errors caused by sync→async bridging.
        self._dedicated_loop = asyncio.new_event_loop()
        self._dedicated_thread = threading.Thread(
            target=self._dedicated_loop.run_forever,
            daemon=True,
            name="graphiti-loop",
        )
        self._dedicated_thread.start()
        logger.info("GraphitiMemoryStore created (workspace={})", workspace)

    # ── dedicated-loop helpers ────────────────────────────────────────────────

    def _run_sync(self, coro: Any, timeout: float = 60) -> Any:
        """Run *coro* on the dedicated loop, blocking the calling thread."""
        future = asyncio.run_coroutine_threadsafe(coro, self._dedicated_loop)
        return future.result(timeout=timeout)

    async def _run_on_dedicated(self, coro: Any, timeout: float = 60) -> Any:
        """Schedule *coro* on the dedicated loop and ``await`` it from any loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self._dedicated_loop)
        return await asyncio.wrap_future(future)

    # ── internal (always runs on the dedicated loop) ─────────────────────────

    async def _ensure_graphiti(self) -> None:
        """Lazily create the Graphiti instance on the dedicated loop."""
        if self._graphiti is not None:
            return

        Graphiti = _lazy_import_graphiti()

        db_kwargs = (
            _resolve_graph_db(self._graph_db_cfg, self.workspace)
            if self._graph_db_cfg
            else {"uri": "bolt://localhost:7687", "user": "neo4j", "password": "password"}
        )

        self._graphiti = Graphiti(
            llm_client=_build_llm_client(self._llm_cfg) if self._llm_cfg else None,
            embedder=_build_embedder(self._embedder_cfg) if self._embedder_cfg else None,
            cross_encoder=(
                _build_cross_encoder(self._cross_encoder_cfg)
                if self._cross_encoder_cfg
                else None
            ),
            **db_kwargs,
        )
        self._initialized = False
        logger.debug("Graphiti instance created on dedicated loop")

    async def _ensure_indices(self) -> None:
        """Ensure Graphiti instance exists and indices are built (once)."""
        await self._ensure_graphiti()
        if self._initialized:
            return
        await self._graphiti.build_indices_and_constraints()
        self._initialized = True
        logger.info("Graphiti indices ready")

    @staticmethod
    def _messages_to_episode_body(messages: list[dict[str, Any]]) -> str:
        lines = []
        for m in messages:
            content = m.get("content", "")
            if not content or not isinstance(content, str):
                continue
            if m.get("role") not in ("user", "assistant"):
                continue
            role = m.get("role", "user").capitalize()
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _edge_to_dict(edge: Any) -> dict[str, Any]:
        return {
            "id": str(getattr(edge, "uuid", "")),
            "memory": getattr(edge, "fact", str(edge)),
            "valid_at": str(getattr(edge, "valid_at", "")),
            "invalid_at": str(getattr(edge, "invalid_at", "")),
        }

    # ── CRUD (internal, runs on dedicated loop) ────────────────────────────────

    async def _add_impl(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
    ) -> Any:
        await self._ensure_indices()
        body = self._messages_to_episode_body(messages)
        if not body:
            return {}
        from graphiti_core.nodes import EpisodeType
        result = await self._graphiti.add_episode(
            name=f"Conversation ({user_id})",
            episode_body=body,
            source_description="nanobot conversation",
            reference_time=datetime.now(timezone.utc),
            source=EpisodeType.message,
            group_id=user_id,
        )
        logger.info("Graphiti add_episode done result={}", result)
        return result

    async def _search_impl(
        self,
        query: str,
        user_id: str = "default",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        await self._ensure_indices()
        edges = await self._graphiti.search(
            query=query,
            group_ids=[user_id],
            num_results=limit,
        )
        result = [self._edge_to_dict(e) for e in edges]
        logger.info("Graphiti search success: {} results", len(result))
        return result

    async def _delete_impl(self, memory_id: str) -> bool:
        await self._ensure_indices()
        await self._graphiti.delete_episode(memory_id)
        return True

    # ── CRUD (public, routes to dedicated loop) ──────────────────────────────

    async def add(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
        **kwargs: Any,
    ) -> Any:
        """Add a conversation episode to the knowledge graph."""
        try:
            return await self._run_on_dedicated(self._add_impl(messages, user_id))
        except Exception:
            logger.exception("Graphiti add_episode failed")
            raise

    async def search(
        self,
        query: str,
        user_id: str = "default",
        limit: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Hybrid semantic + keyword search over the knowledge graph."""
        try:
            return await self._run_on_dedicated(self._search_impl(query, user_id, limit))
        except Exception:
            logger.exception("Graphiti search failed")
            return []

    async def get_all(
        self,
        user_id: str = "default",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Return recent facts via a broad search (Graphiti has no 'get_all' API)."""
        return await self.search("*", user_id=user_id, limit=kwargs.get("limit", 50))

    async def update(self, memory_id: str, content: str, **kwargs: Any) -> bool:
        """Graphiti uses fact invalidation instead of in-place updates."""
        logger.warning(
            "GraphitiMemoryStore.update: Graphiti uses fact invalidation, "
            "not in-place updates. Add a new episode to supersede old facts."
        )
        return False

    async def delete(self, memory_id: str, **kwargs: Any) -> bool:
        """Delete an edge (fact) by UUID."""
        try:
            return await self._run_on_dedicated(self._delete_impl(memory_id))
        except Exception:
            logger.exception("Graphiti delete failed for memory_id={}", memory_id)
            return False

    # ── Agent prompt integration ──────────────────────────────────────────────

    def get_memory_context(self, **kwargs: Any) -> str:
        """Build context string from recent facts.

        Uses the dedicated loop directly (blocking) — safe to call from
        any thread or from within a running event loop.
        """
        query = kwargs.get("query", "")
        user_id = kwargs.get("user_id", "default")
        limit = kwargs.get("limit", 10)
        try:
            memories = self._run_sync(self._search_impl(query, user_id=user_id, limit=limit))
            if not memories:
                return ""
            lines = [f"- {m['memory']}" for m in memories if m.get("memory")]
            return "## Long-term Memory (Graphiti Knowledge Graph)\n" + "\n".join(lines)
        except Exception:
            logger.exception("Graphiti get_memory_context failed")
            return ""

    # ── Consolidation ─────────────────────────────────────────────────────────

    async def consolidate(
        self,
        messages: list[dict[str, Any]],
        provider: LLMProvider,
        model: str,
        user_id: str = "default",
    ) -> bool:
        """Consolidate messages by adding them as a Graphiti episode."""
        if not messages:
            return True
        try:
            await self.add(messages, user_id=user_id)
            self._consecutive_failures = 0
            logger.info("Graphiti consolidation done for {} messages", len(messages))
            return True
        except Exception:
            logger.exception("Graphiti consolidation failed")
            return self._fail_or_raw_archive(messages)

async def main() -> None:
    from nanobot.agent.memory import create_memory_store_from_config
    from nanobot.config.loader import load_config

    _config = load_config()
    _store = create_memory_store_from_config(_config.memory, _config.workspace_path)

    _messages = [
        {"role": "user", "content": "我叫李明，是一名软件工程师"},
        {"role": "assistant", "content": "你好李明，很高兴认识你！"},
        {"role": "user", "content": "我喜欢用Python做数据分析"},
    ]
    await _store.add(
        messages=_messages,
        user_id="test_user"
    )
    await _store.search(
        query="李明的职业",
        user_id="test_user"
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
