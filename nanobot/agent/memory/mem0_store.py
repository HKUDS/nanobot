"""Mem0 memory store adapter.

Wraps the `mem0ai` library to provide a universal memory layer for AI agents.
Mem0 supports multi-level memory (user, session, agent), graph memory, and
intelligent memory extraction with automatic deduplication and conflict resolution.

Install: ``pip install mem0ai``

Reference: https://github.com/mem0ai/mem0
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.memory.base import BaseMemoryStore

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


def _lazy_import_mem0():
    """Import the mem0ai Memory class and return it.

    Raises ImportError immediately if mem0ai is not installed, so callers
    get a clear message at construction time rather than on first use.

    Note: This file must NOT be named ``mem0.py`` to avoid shadowing the
    installed ``mem0`` package.
    """
    try:
        import importlib
        mem0_pkg = importlib.import_module("mem0")
        Memory = getattr(mem0_pkg, "Memory")
        return Memory
    except (ImportError, AttributeError):
        raise ImportError(
            "mem0ai is required for Mem0MemoryStore. "
            "Install it with: pip install mem0ai"
        )


# ── Config normalisation helpers ─────────────────────────────────────────────

import re as _re


def _camel_to_snake(name: str) -> str:
    """Convert a single camelCase string to snake_case."""
    s = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = _re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def _deep_camel_to_snake(obj: Any) -> Any:
    """Recursively convert every dict key in *obj* from camelCase to snake_case."""
    if isinstance(obj, dict):
        return {_camel_to_snake(k): _deep_camel_to_snake(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_camel_to_snake(i) for i in obj]
    return obj


# Keys that mem0's OpenAI provider config uses, mapped from generic aliases.
_OPENAI_BASE_URL_ALIASES = ("api_base", "base_url", "openai_api_base")



def _normalize_mem0_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalise a mem0 config dict before passing it to ``Memory.from_config``.

    Steps applied in order:

    1. Deep-convert all keys from camelCase to snake_case (``apiKey`` → ``api_key``).
    2. For ``llm.config`` and ``embedder.config`` under an OpenAI-compatible
       provider, remap ``api_base`` / ``base_url`` aliases to ``openai_base_url``
       (the key that mem0's ``OpenAIConfig`` and ``BaseEmbedderConfig`` actually use).
    3. Accept ``embedding`` / ``embeddings`` as an alias for ``embedder``.
    4. Auto-derive a minimal ``embedder`` section from the ``llm`` section when
       the caller did not provide one, so the same API key / base URL is reused
       for embeddings without requiring a separate ``OPENAI_API_KEY`` env var.
    """
    cfg: dict[str, Any] = _deep_camel_to_snake(config)

    # Remap api_base aliases → openai_base_url for llm + embedder sections
    for section_key in ("llm", "embedder"):
        section = cfg.get(section_key)
        if not isinstance(section, dict):
            continue
        inner: dict[str, Any] = section.get("config") or {}
        if "openai_base_url" not in inner:
            for alias in _OPENAI_BASE_URL_ALIASES:
                if alias in inner:
                    inner["openai_base_url"] = inner.pop(alias)
                    break
        section["config"] = inner
        cfg[section_key] = section

    # Auto-derive embedder from llm when not present
    if "llm" in cfg and "embedder" not in cfg:
        llm_inner: dict[str, Any] = cfg["llm"].get("config") or {}
        embedder_cfg: dict[str, Any] = {}
        if llm_inner.get("api_key"):
            embedder_cfg["api_key"] = llm_inner["api_key"]
        if llm_inner.get("openai_base_url"):
            embedder_cfg["openai_base_url"] = llm_inner["openai_base_url"]
        if embedder_cfg:
            cfg["embedder"] = {"provider": "openai", "config": embedder_cfg}
            logger.debug("Mem0: auto-derived embedder config from llm section")

    return cfg


class Mem0MemoryStore(BaseMemoryStore):
    """Memory store backed by the Mem0 framework.

    Mem0 provides an intelligent memory layer with:
    - Automatic memory extraction from conversations
    - Semantic search with vector embeddings
    - Memory deduplication and conflict resolution
    - Optional graph-based memory for relationship tracking

    Initialization strategy
    -----------------------
    The underlying ``mem0.Memory`` instance is created lazily:

    * If *config* contains an ``"llm"`` key, the instance is created
      immediately at ``__init__`` time using that config.
    * Otherwise, instantiation is deferred until the first call to any
      method.  When :meth:`consolidate` is called it passes *provider* and
      *model*, which are used to build a minimal mem0 llm config so no
      external ``OPENAI_API_KEY`` is needed.

    Args:
        workspace: Path to the workspace directory.
        config: Optional Mem0 configuration dict.  When ``None`` (or when the
                dict has no ``"llm"`` key), the nanobot LLM provider passed to
                :meth:`consolidate` is used as a fallback.
                See https://docs.mem0.ai/overview for full configuration docs.

    Example config (camelCase or snake_case keys are both accepted; ``embedding``
    is accepted as an alias for ``embedder``)::

        config = {
            "llm": {
                "provider": "openai",
                "config": {
                    "model": "gpt-4o-mini",
                    "apiKey": "sk-...",        # or api_key
                    "apiBase": "https://...",  # or openai_base_url
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": "text-embedding-3-large",
                    "apiKey": "sk-...",
                    "apiBase": "https://...",
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {"collection_name": "nanobot_memories", "host": "localhost","port": 6333,"embedding_model_dims":2560},
            },
        }
    """

    def __init__(self, workspace: Path, *, config: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__(workspace)
        # Import the class now so that a missing mem0ai package fails fast.
        self._Memory: Any = _lazy_import_mem0()
        # Support two calling conventions:
        #   Direct:  Mem0MemoryStore(workspace, config={"llm": ..., "vector_store": ...})
        #   Factory: create_memory_store("mem0", llm={...}, vector_store={...})
        #            → the factory unpacks backend_settings as **kwargs, so config=None here.
        effective_config: dict[str, Any] | None = (
            config if config is not None else (kwargs if kwargs else None)
        )
        # Store the normalised config so _ensure_initialized always sees clean keys.
        self._mem0_raw_config: dict[str, Any] | None = (
            _normalize_mem0_config(effective_config) if effective_config else None
        )
        self._mem0: Any | None = None

        # Eagerly instantiate only when the config already provides LLM settings.
        # This avoids hitting OpenAI's API-key check for users who rely on the
        # provider-fallback path (triggered via consolidate()).
        if self._mem0_raw_config and "llm" in self._mem0_raw_config:
            self._mem0 = self._Memory.from_config(self._mem0_raw_config)
            logger.info("Mem0MemoryStore initialized with config (workspace={})", workspace)
        else:
            logger.info(
                "Mem0MemoryStore created — will init on first use (workspace={})", workspace
            )

    # ── Lazy initialisation ──────────────────────────────────────────────

    def _ensure_initialized(
        self,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        """Ensure ``self._mem0`` is ready, building config from *provider* if needed."""
        if self._mem0 is not None:
            return

        cfg: dict[str, Any] = dict(self._mem0_raw_config or {})

        if "llm" not in cfg:
            if provider is not None:
                cfg.update(self._build_fallback_config(provider, model or ""))
                logger.info(
                    "Mem0MemoryStore: using nanobot LLMProvider fallback (model={})", model
                )
            # If neither config nor provider is available, call Memory() with no
            # arguments — mem0 will fall back to its own defaults (may require
            # OPENAI_API_KEY in the environment).

        if cfg:
            self._mem0 = self._Memory.from_config(cfg)
        else:
            self._mem0 = self._Memory()

    @staticmethod
    def _build_fallback_config(provider: LLMProvider, model: str) -> dict[str, Any]:
        """Build a minimal mem0 llm + embedder config from a nanobot LLMProvider.

        Both the LLM and the embedder are pointed at the same OpenAI-compatible
        endpoint so that no separate embedding API key is required.
        Uses the key names that mem0's OpenAIConfig / BaseEmbedderConfig expect:
        ``api_key`` and ``openai_base_url``.
        """
        llm_cfg: dict[str, Any] = {"model": model}
        if provider.api_key:
            llm_cfg["api_key"] = provider.api_key
        if provider.api_base:
            llm_cfg["openai_base_url"] = provider.api_base

        embedder_cfg: dict[str, Any] = {"model": "text-embedding-3-small"}
        if provider.api_key:
            embedder_cfg["api_key"] = provider.api_key
        if provider.api_base:
            embedder_cfg["openai_base_url"] = provider.api_base

        return {
            "llm": {"provider": "openai", "config": llm_cfg},
            "embedder": {"provider": "openai", "config": embedder_cfg},
        }

    # ── Core CRUD ────────────────────────────────────────────────────────

    async def add(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
        **kwargs: Any,
    ) -> Any:
        """Add memories from conversation messages via Mem0's extraction pipeline.

        Mem0 automatically extracts facts, preferences, and context from the
        messages and stores them with deduplication.
        """
        self._ensure_initialized()
        result = await asyncio.to_thread(
            self._mem0.add, messages, user_id=user_id, **kwargs
        )
        count = len(result.get("results", [])) if isinstance(result, dict) else 0
        logger.debug("Mem0 add: extracted {} memories for user={}", count, user_id)
        return result

    async def search(
        self,
        query: str,
        user_id: str = "default",
        limit: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Semantic search over stored memories."""
        self._ensure_initialized()
        result = await asyncio.to_thread(
            self._mem0.search, query=query, user_id=user_id, limit=limit, **kwargs
        )
        memories = result.get("results", []) if isinstance(result, dict) else result
        logger.info("Memory search result:{}", memories)
        return memories if isinstance(memories, list) else []

    async def get_all(
        self,
        user_id: str = "default",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Retrieve all memories for a user."""
        self._ensure_initialized()
        result = await asyncio.to_thread(
            self._mem0.get_all, user_id=user_id, **kwargs
        )
        memories = result.get("results", []) if isinstance(result, dict) else result
        return memories if isinstance(memories, list) else []

    async def update(self, memory_id: str, content: str, **kwargs: Any) -> bool:
        """Update an existing memory entry in Mem0."""
        self._ensure_initialized()
        try:
            await asyncio.to_thread(self._mem0.update, memory_id, content)
            return True
        except Exception:
            logger.exception("Mem0 update failed for memory_id={}", memory_id)
            return False

    async def delete(self, memory_id: str, **kwargs: Any) -> bool:
        """Delete a memory entry from Mem0."""
        self._ensure_initialized()
        try:
            await asyncio.to_thread(self._mem0.delete, memory_id)
            return True
        except Exception:
            logger.exception("Mem0 delete failed for memory_id={}", memory_id)
            return False

    def get_memory_context(self, **kwargs: Any) -> str:
        """Build context by fetching all memories for the default user."""
        self._ensure_initialized()
        user_id = kwargs.get("user_id", "default")
        try:
            result = self._mem0.get_all(user_id=user_id)
            memories = result.get("results", []) if isinstance(result, dict) else result
            if not memories:
                return ""
            lines = [f"- {m.get('memory', m.get('content', ''))}" for m in memories if m]
            logger.info("Memory0 get_memory_context:{}", lines)
            return "## Long-term Memory (Mem0)\n" + "\n".join(lines)
        except Exception:
            logger.exception("Mem0 get_memory_context failed")
            return ""

    async def consolidate(
        self,
        messages: list[dict[str, Any]],
        provider: LLMProvider,
        model: str,
        user_id: str = "default",
    ) -> bool:
        """Consolidate messages by feeding them into Mem0's add pipeline.

        Mem0 handles extraction, deduplication, and conflict resolution internally,
        so we delegate all consolidation logic to it.

        If no LLM config was provided at construction time, the nanobot
        *provider* / *model* are used to build one on first call.
        """
        if not messages:
            return True
        try:
            self._ensure_initialized(provider, model)
            mem0_messages = []
            for msg in messages:
                content = msg.get("content", "")
                if not content:
                    continue
                role = msg.get("role", "user")
                mem0_messages.append({"role": role, "content": content})

            if mem0_messages:
                await self.add(mem0_messages, user_id=user_id)
            self._consecutive_failures = 0
            logger.info("Mem0 consolidation done for {} messages", len(messages))
            return True
        except Exception:
            logger.exception("Mem0 consolidation failed")
            return self._fail_or_raw_archive(messages)


if __name__ == "__main__":
    from nanobot.agent.memory import create_memory_store_from_config
    from nanobot.config.loader import load_config

    _config = load_config()
    _workspace = _config.workspace_path
    _store = create_memory_store_from_config(_config.memory, _workspace)

    _messages = [
        {"role": "user", "content": "今天天气怎么样"},
        {"role": "user", "content": "天气晴朗"},
        {"role": "user", "content": "我想看新龙城的房子"},
        {"role": "user", "content": "回龙观怎么样"},
        {"role": "user", "content": "香港旅游攻略"},
        {"role": "user", "content": "试试"},
    ]
    asyncio.run(_store.add(_messages))
    asyncio.run(_store.search(
        query="天气"))