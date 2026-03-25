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

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.memory.base import BaseMemoryStore
import graphiti_core

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


def _strip_markdown_json(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fences from LLM output.

    Some OpenAI-compatible proxy APIs ignore ``response_format: json_object``
    and wrap the JSON payload in markdown code fences.  This helper extracts
    the raw JSON so that ``json.loads`` can parse it.
    """
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence line (e.g. "```json\n" or "```\n")
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
        # Remove closing fence
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    return text.strip()


def _build_llm_client(llm_cfg: dict[str, Any]):
    """Build a Graphiti LLMClient from a config dict.

    Returns a subclass of ``OpenAIGenericClient`` that automatically strips
    markdown code fences from LLM responses before JSON parsing.  This is
    needed for OpenAI-compatible proxy APIs that ignore ``response_format``
    and wrap JSON output in triple-backtick fences.
    """
    import json as _json
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
    from graphiti_core.llm_client.config import LLMConfig

    cfg = _normalize_keys(llm_cfg)
    config = LLMConfig(
        api_key=cfg.get("api_key"),
        model=cfg.get("model"),
        small_model=cfg.get("small_model", cfg.get("model")),
        base_url=cfg.get("base_url"),
    )

    class _MarkdownStrippingClient(OpenAIGenericClient):
        """OpenAIGenericClient that tolerates markdown-fenced / bare-list JSON responses.

        Two problems this fixes:

        1. Proxy APIs that ignore ``response_format`` and wrap JSON in
           triple-backtick fences — we strip the fences before parsing.

        2. Proxy APIs that return a bare JSON array ``[...]`` when Graphiti
           expects a dict ``{"entities": [...]}`` — we detect the list field
           from ``response_model`` and wrap automatically.
        """

        # ── LLM often uses slightly different key names than the schema expects.
        # Map common substitutions so Pydantic validation succeeds.
        _FIELD_ALIASES: dict[str, str] = {
            # entity name variations
            "entity": "name",
            "entity_name": "name",
            "label": "name",
            "node": "name",
            "subject": "name",
            "title": "name",
            "text": "name",
            "value": "name",
            # edge fact / description variations
            "description": "fact",
            "relationship": "fact",
            "relation_description": "fact",
            "predicate": "fact",
            "statement": "fact",
            "claim": "fact",
            "summary": "fact",
        }

        @staticmethod
        def _get_item_model(response_model, field_name: str):
            """Return the inner Pydantic model class for a list field, or None."""
            finfo = response_model.model_fields.get(field_name)
            if finfo is None:
                return None
            args = getattr(finfo.annotation, "__args__", None)
            if args and len(args) == 1 and hasattr(args[0], "model_fields"):
                return args[0]
            return None

        @staticmethod
        def _synthesize_missing(item: dict, item_model) -> dict:
            """Synthesize fields that can be derived from other fields already present.

            Currently handles:
            * ``fact`` — derived from ``source_entity_name + relation_type +
              target_entity_name`` when the LLM omits it entirely.
            """
            if item_model is None or not isinstance(item, dict):
                return item
            try:
                required_missing = {
                    k for k in item_model.model_fields
                    if k not in item and item_model.model_fields[k].is_required()
                }
                if not required_missing:
                    return item
                result = dict(item)
                if "fact" in required_missing:
                    src = result.get("source_entity_name", "")
                    rel = result.get("relation_type", "")
                    tgt = result.get("target_entity_name", "")
                    if src or rel or tgt:
                        result["fact"] = f"{src} {rel} {tgt}".strip()
                return result
            except Exception:
                return item

        @staticmethod
        def _normalize_item(item: dict, item_model) -> dict:
            """Remap keys in one list item so they match item_model's field names,
            then synthesize any remaining required fields that can be derived."""
            if item_model is None or not isinstance(item, dict):
                return item
            try:
                expected = set(item_model.model_fields.keys())
                unknown = set(item.keys()) - expected
                result = dict(item)

                if unknown:
                    aliases = _MarkdownStrippingClient._FIELD_ALIASES
                    missing = expected - set(result.keys())

                    for old_key in list(unknown):
                        mapped = aliases.get(old_key)
                        if mapped and mapped in missing:
                            result[mapped] = result.pop(old_key)
                            missing.discard(mapped)

                    # Last-resort: if exactly one unknown key remains and one required
                    # field is still absent, assume they correspond to each other.
                    remaining_unknown = set(result.keys()) - expected
                    required_missing = {
                        k for k in (expected - set(result.keys()))
                        if item_model.model_fields[k].is_required()
                    }
                    if len(remaining_unknown) == 1 and len(required_missing) == 1:
                        old = next(iter(remaining_unknown))
                        new = next(iter(required_missing))
                        result[new] = result.pop(old)

                # Synthesize fields that are still missing but can be derived
                result = _MarkdownStrippingClient._synthesize_missing(result, item_model)
                return result
            except Exception:
                return item

        @staticmethod
        def _normalize_top_level_keys(parsed: dict, response_model) -> dict:
            """Remap top-level dict keys that don't match response_model fields.

            LLMs sometimes return wrong top-level key names, e.g.
            ``{"duplicate_facts": [...]}`` instead of ``{"summaries": [...]}``.
            We find the first list field in response_model and remap any
            unknown list-valued key to it.
            """
            if response_model is None or not isinstance(parsed, dict):
                return parsed
            expected_keys = set(response_model.model_fields.keys())
            unknown_keys = set(parsed.keys()) - expected_keys
            if not unknown_keys:
                return parsed

            result = dict(parsed)
            # Find expected list fields that are missing from the response
            missing_list_fields = [
                fname for fname, finfo in response_model.model_fields.items()
                if fname not in result
                and getattr(finfo.annotation, "__origin__", None) is list
            ]
            for missing_field in missing_list_fields:
                # Find an unknown key whose value is a list — remap it
                for uk in list(unknown_keys):
                    if isinstance(result.get(uk), list):
                        result[missing_field] = result.pop(uk)
                        unknown_keys.discard(uk)
                        break
            return result

        @staticmethod
        def _normalize_list_items_in_dict(parsed: dict, response_model) -> dict:
            """When the LLM returns a correctly shaped dict, still normalise the
            field names inside each item of every list field."""
            if response_model is None or not isinstance(parsed, dict):
                return parsed
            result = dict(parsed)
            for fname, finfo in response_model.model_fields.items():
                if fname not in result:
                    continue
                if getattr(finfo.annotation, "__origin__", None) is not list:
                    continue
                item_model = _MarkdownStrippingClient._get_item_model(response_model, fname)
                if item_model is None or not isinstance(result[fname], list):
                    continue
                result[fname] = [
                    _MarkdownStrippingClient._normalize_item(it, item_model)
                    for it in result[fname]
                ]
            return result

        @staticmethod
        def _wrap_list_if_needed(result, response_model) -> dict:
            """If the parsed result is a bare list, wrap it in the key expected by
            response_model and normalise each item's field names."""
            if not isinstance(result, list):
                return result  # already a dict — handled by _normalize_list_items_in_dict
            if response_model is None:
                return {"items": result}

            # Find the first field whose annotation is list[...]
            field_name: str | None = None
            for fname, finfo in response_model.model_fields.items():
                if getattr(finfo.annotation, "__origin__", None) is list:
                    field_name = fname
                    break
            if field_name is None:
                field_name = next(iter(response_model.model_fields), "items")

            item_model = _MarkdownStrippingClient._get_item_model(response_model, field_name)
            normalized = [
                _MarkdownStrippingClient._normalize_item(item, item_model)
                for item in result
            ]
            return {field_name: normalized}

        async def _generate_response(self, messages, response_model=None, **kw):
            import graphiti_core.llm_client.openai_generic_client as _mod
            original_loads = _mod.json.loads

            def _safe_loads(text, *args, **kwargs):
                if isinstance(text, str):
                    text = _strip_markdown_json(text)
                parsed = original_loads(text, *args, **kwargs)
                # Case 1: LLM returned a bare list → wrap in the expected dict key
                parsed = _MarkdownStrippingClient._wrap_list_if_needed(parsed, response_model)
                # Case 2: LLM returned a dict → normalise item field names in list fields
                if isinstance(parsed, dict):
                    parsed = _MarkdownStrippingClient._normalize_list_items_in_dict(
                        parsed, response_model
                    )
                return parsed

            _mod.json.loads = _safe_loads
            try:
                return await super()._generate_response(messages, response_model, **kw)
            finally:
                _mod.json.loads = original_loads

    return _MarkdownStrippingClient(config=config)


def _build_embedder(embedder_cfg: dict[str, Any]):
    """Build a Graphiti EmbedderClient from a config dict."""
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

    cfg = _normalize_keys(embedder_cfg)
    return OpenAIEmbedder(config=OpenAIEmbedderConfig(
        api_key=cfg.get("api_key"),
        embedding_model=cfg.get("model", cfg.get("embedding_model")),
        embedding_dim=int(cfg.get("embedding_dim", cfg.get("embedding_dims", 1536))),
        base_url=cfg.get("base_url"),
    ))

def _build_cross_encoder(cross_encoder_cfg: dict[str, Any]):
    """Build a Graphiti EmbedderClient from a config dict."""
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.llm_client.config import LLMConfig

    cfg = _normalize_keys(cross_encoder_cfg)
    return OpenAIRerankerClient(config=LLMConfig(
        api_key=cfg.get("api_key"),
        model=cfg.get("model"),
        small_model=cfg.get("small_model", cfg.get("model")),
        base_url=cfg.get("base_url"),
    ))


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

    # Find the single enabled backend
    enabled_db: str | None = None
    enabled_cfg: dict[str, Any] = {}
    for db_name, db_conf in cfg.items():
        if not isinstance(db_conf, dict):
            continue
        # accept "enable" or "enabled"
        if db_conf.get("enable", db_conf.get("enabled", False)):
            if enabled_db is not None:
                raise ValueError(
                    f"Multiple graph_db backends enabled: '{enabled_db}' and '{db_name}'. "
                    "Only one may be enabled at a time."
                )
            enabled_db = db_name
            enabled_cfg = db_conf

    if enabled_db is None:
        # Default to Neo4j with localhost defaults
        logger.warning("No graph_db backend enabled in config, defaulting to Neo4j localhost")
        return {"uri": "bolt://localhost:7687", "user": "neo4j", "password": "password"}

    db_type = enabled_db.lower()

    if db_type == "neo4j":
        # Support both "url" and "uri" keys
        uri = enabled_cfg.get("url") or enabled_cfg.get("uri", "bolt://localhost:7687")
        kwargs: dict[str, Any] = {
            "uri": uri,
            "user": enabled_cfg.get("user", "neo4j"),
            "password": enabled_cfg.get("password", "password"),
        }
        # Graphiti accepts database name via a custom Neo4jDriver
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

    Graphiti stores facts as edges in a knowledge graph, each with a validity
    window.  When information changes, old facts are invalidated (not deleted),
    so the agent can always query what was true at any point in time.

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
                }
            },

            "llm": {
                "model": "gpt-4o-mini",
                "apiKey": "sk-...",
                "baseUrl": "https://..."
            },

            "embedder": {
                "model": "text-embedding-3-small",
                "apiKey": "sk-...",
                "baseUrl": "https://...",
                "embeddingDim": 1536
            }
        }

    Alternative graph DB backends::

        # FalkorDB (simpler, one-liner Docker)
        # docker run -p 6379:6379 -p 3000:3000 --rm falkordb/falkordb:latest
        "graph_db": {
            "falkordb": {
                "enable": true,
                "host": "localhost",
                "port": 6379
            }
        }

        # Kuzu (embedded, no server needed)
        "graph_db": {
            "kuzu": {
                "enable": true,
                "dbPath": "./graphiti_kuzu"
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
        # Store raw config; Graphiti instance is created lazily on the first
        # async call so that its internal connection pools are always bound to
        # the running event loop (avoids "Future attached to a different loop").
        self._graph_db_cfg = graph_db
        self._llm_cfg = llm
        self._embedder_cfg = embedder
        self._cross_encoder_cfg = cross_encoder
        self._graphiti: Any = None
        self._loop: Any = None   # event loop the current _graphiti instance belongs to
        self._initialized = False
        logger.info("GraphitiMemoryStore created (workspace={})", workspace)

    # ── internal ─────────────────────────────────────────────────────────────

    async def _ensure_graphiti(self) -> None:
        """Lazily create (or recreate) the Graphiti instance for the current event loop.

        FalkorDB (and other async graph drivers) bind their connection pools to
        the event loop that is active at construction time.  Creating the
        instance here — inside an awaited call — guarantees it shares the loop
        used by all subsequent operations.

        If called from a *different* event loop than the one that last created
        the instance (e.g. when ``get_memory_context`` bridges via a thread +
        ``asyncio.run``), we transparently recreate the instance so the new
        connections are bound to the correct loop.
        """
        import asyncio
        current_loop = asyncio.get_running_loop()

        # Recreate if the instance belongs to a different (possibly closed) loop
        if self._graphiti is not None and self._loop is current_loop:
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
        self._loop = current_loop
        # Indices must be (re-)built for the new instance
        self._initialized = False
        logger.debug("Graphiti instance created/refreshed for event loop {}", id(current_loop))

    async def _ensure_indices(self) -> None:
        """Ensure Graphiti instance exists and indices are built (once per loop)."""
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
            if not content:
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

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def add(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
        **kwargs: Any,
    ) -> Any:
        """Add a conversation episode to the knowledge graph."""
        await self._ensure_indices()
        body = self._messages_to_episode_body(messages)
        if not body:
            return {}
        try:
            from graphiti_core.nodes import EpisodeType
            result = await self._graphiti.add_episode(
                name=f"Conversation ({user_id})",
                episode_body=body,
                source_description="nanobot conversation",
                reference_time=datetime.now(timezone.utc),
                source=EpisodeType.message,
                group_id=user_id,
            )
            logger.debug("Graphiti add_episode done for user={}", user_id)
            return result
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
        await self._ensure_indices()
        try:
            edges = await self._graphiti.search(
                query=query,
                group_ids=[user_id],
                num_results=limit,
            )
            return [self._edge_to_dict(e) for e in edges]
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
        await self._ensure_indices()
        try:
            await self._graphiti.delete_episode(memory_id)
            return True
        except Exception:
            logger.exception("Graphiti delete failed for memory_id={}", memory_id)
            return False

    # ── Agent prompt integration ──────────────────────────────────────────────

    def get_memory_context(self, **kwargs: Any) -> str:
        """Build context string from recent facts (runs synchronously via search)."""
        import asyncio
        query = kwargs.get("query", "")
        user_id = kwargs.get("user_id", "default")
        limit = kwargs.get("limit", 10)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.search(query, user_id=user_id, limit=limit))
                    memories = future.result(timeout=30)
            else:
                memories = loop.run_until_complete(self.search(query, user_id=user_id, limit=limit))
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
    ) -> bool:
        """Consolidate messages by adding them as a Graphiti episode."""
        if not messages:
            return True
        try:
            await self.add(messages)
            self._consecutive_failures = 0
            logger.info("Graphiti consolidation done for {} messages", len(messages))
            return True
        except Exception:
            logger.exception("Graphiti consolidation failed")
            return self._fail_or_raw_archive(messages)


if __name__ == "__main__":
    import asyncio
    from nanobot.agent.memory import create_memory_store_from_config
    from nanobot.config.loader import load_config

    _config = load_config()
    _store = create_memory_store_from_config(_config.memory, _config.workspace_path)

    _messages = [
        {"role": "user", "content": "我叫李明，是一名软件工程师"},
        {"role": "assistant", "content": "你好李明，很高兴认识你！"},
        {"role": "user", "content": "我喜欢用Python做数据分析"},
    ]
    asyncio.run(_store.add(_messages))
    results = asyncio.run(_store.search("李明的职业"))
    for r in results:
        print(r["memory"])
