"""Memory subsystem for nanobot agents.

Provides a pluggable memory architecture with a common ``BaseMemoryStore``
interface and multiple backend implementations:

- **LongTermMemoryStore** — Original file-based memory (MEMORY.md + HISTORY.md)
- **Mem0MemoryStore**     — Mem0 framework (vector DB + graph memory)
- **LightMemoryStore**    — LightMem framework (compression + topic segmentation)
- **AgenticMemoryStore**  — A-MEM framework (Zettelkasten-style agentic memory)
- **SimpleMemoryStore**   — SimpleMem framework (semantic lossless compression)

Quick start::

    from nanobot.agent.memory import create_memory_store
    store = create_memory_store("long_term", workspace=Path("./workspace"))

Backward compatibility: ``MemoryStore`` and ``MemoryConsolidator`` are still
importable from this module and behave identically to the originals.
"""

from __future__ import annotations

import asyncio
import re
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from nanobot.agent.memory.base import BaseMemoryStore
from nanobot.agent.memory.long_term_memory import LongTermMemoryStore

if TYPE_CHECKING:
    from nanobot.config.schema import MemoryConfig
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session, SessionManager

# ── Registry of available backends ───────────────────────────────────────

MEMORY_BACKENDS: dict[str, str] = {
    "long_term": "nanobot.agent.memory.long_term_memory.LongTermMemoryStore",
    "mem0": "nanobot.agent.memory.mem0_store.Mem0MemoryStore",
    "lightmem": "nanobot.agent.memory.light_memory.LightMemoryStore",
    "a_mem": "nanobot.agent.memory.agentic_memory.AgenticMemoryStore",
    "simplemem": "nanobot.agent.memory.simple_memory.SimpleMemoryStore",
    "graphiti": "nanobot.agent.memory.graphiti_store.GraphitiMemoryStore",
    "memobase": "nanobot.agent.memory.memobase_store.MemobaseMemoryStore",
}

_CONFIG_KEY_TO_BACKEND: dict[str, str] = {
    "long_term": "long_term",
    "longTerm": "long_term",
    "long_term_memory": "long_term",
    "mem0": "mem0",
    "lightmem": "lightmem",
    "light_mem": "lightmem",
    "lightMem": "lightmem",
    "a_mem": "a_mem",
    "aMem": "a_mem",
    "agentic_memory": "a_mem",
    "simplemem": "simplemem",
    "simpleMem": "simplemem",
    "simple_mem": "simplemem",
    "graphiti": "graphiti",
    "memobase": "memobase",
    "memoBase": "memobase",
}


def _camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def create_memory_store(
    backend: str = "long_term",
    workspace: Path | None = None,
    **kwargs: Any,
) -> BaseMemoryStore:
    """Factory function to create a memory store by backend name.

    Args:
        backend:   One of ``"long_term"``, ``"mem0"``, ``"lightmem"``,
                   ``"a_mem"``, ``"simplemem"``.
        workspace: Path to the agent workspace directory.
        **kwargs:  Backend-specific configuration passed to the constructor.

    Returns:
        An initialized ``BaseMemoryStore`` subclass instance.

    Raises:
        ValueError: If *backend* is not recognized.
        ImportError: If the required third-party library is not installed.
    """
    if backend not in MEMORY_BACKENDS:
        available = ", ".join(sorted(MEMORY_BACKENDS))
        raise ValueError(f"Unknown memory backend '{backend}'. Available: {available}")

    module_path, class_name = MEMORY_BACKENDS[backend].rsplit(".", 1)

    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)

    ws = workspace or Path(".")
    return cls(workspace=ws, **kwargs)


def create_memory_store_from_config(
    memory_config: MemoryConfig,
    workspace: Path,
) -> BaseMemoryStore:
    """Create a memory store driven by the ``memory`` section in config.json.

    Scans all extra fields on *memory_config* for a dict with ``enabled=True``,
    maps it to a registered backend, converts camelCase keys to snake_case,
    and delegates to :func:`create_memory_store`.

    Falls back to :class:`LongTermMemoryStore` when no backend is enabled.

    Raises:
        ValueError: If more than one backend is enabled simultaneously.
    """
    enabled_backend: str | None = None
    backend_settings: dict[str, Any] = {}

    for attr_name, section in (memory_config.model_extra or {}).items():
        if not isinstance(section, dict):
            continue
        if not section.get("enabled", False):
            continue

        backend_key = _CONFIG_KEY_TO_BACKEND.get(attr_name)
        if not backend_key:
            logger.warning("Unknown memory backend in config: {}", attr_name)
            continue
        if enabled_backend is not None:
            raise ValueError(
                f"Multiple memory backends enabled: '{enabled_backend}' and '{backend_key}'. "
                "Only one may be enabled at a time."
            )
        enabled_backend = backend_key
        backend_settings = {
            _camel_to_snake(k): v for k, v in section.items() if k != "enabled"
        }

    if enabled_backend is None:
        logger.info("No memory backend enabled in config, using default long_term")
        return LongTermMemoryStore(workspace)

    logger.info("Creating memory store: backend={}", enabled_backend)
    return create_memory_store(enabled_backend, workspace=workspace, **backend_settings)


# ── Backward-compatible aliases ──────────────────────────────────────────

MemoryStore = LongTermMemoryStore
"""Backward-compatible alias for ``LongTermMemoryStore``."""


class MemoryConsolidator:
    """Owns consolidation policy, locking, and session offset updates.

    Works with any ``BaseMemoryStore`` implementation.
    """

    _MAX_CONSOLIDATION_ROUNDS = 5

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        sessions: SessionManager,
        context_window_tokens: int,
        build_messages: Callable[..., list[dict[str, Any]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        *,
        store: BaseMemoryStore | None = None,
    ):
        self.store = store or LongTermMemoryStore(workspace)
        self.provider = provider
        self.model = model
        self.sessions = sessions
        self.context_window_tokens = context_window_tokens
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get_lock(self, session_key: str) -> asyncio.Lock:
        return self._locks.setdefault(session_key, asyncio.Lock())

    async def consolidate_messages(self, messages: list[dict[str, object]]) -> bool:
        return await self.store.consolidate(messages, self.provider, self.model)

    def pick_consolidation_boundary(
        self,
        session: Session,
        tokens_to_remove: int,
    ) -> tuple[int, int] | None:
        from nanobot.utils.helpers import estimate_message_tokens

        start = session.last_consolidated
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None

        removed_tokens = 0
        last_boundary: tuple[int, int] | None = None
        for idx in range(start, len(session.messages)):
            message = session.messages[idx]
            if idx > start and message.get("role") == "user":
                last_boundary = (idx, removed_tokens)
                if removed_tokens >= tokens_to_remove:
                    return last_boundary
            removed_tokens += estimate_message_tokens(message)

        return last_boundary

    def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        from nanobot.utils.helpers import estimate_prompt_tokens_chain

        history = session.get_history(max_messages=0)
        channel, chat_id = (
            session.key.split(":", 1) if ":" in session.key else (None, None)
        )
        probe_messages = self._build_messages(
            history=history,
            current_message="[token-probe]",
            channel=channel,
            chat_id=chat_id,
        )
        return estimate_prompt_tokens_chain(
            self.provider,
            self.model,
            probe_messages,
            self._get_tool_definitions(),
        )

    async def archive_messages(self, messages: list[dict[str, object]]) -> bool:
        if not messages:
            return True
        for _ in range(self.store._MAX_FAILURES_BEFORE_RAW_ARCHIVE):
            if await self.consolidate_messages(messages):
                return True
        return True

    async def maybe_consolidate_by_tokens(self, session: Session) -> None:
        if not session.messages or self.context_window_tokens <= 0:
            return

        lock = self.get_lock(session.key)
        async with lock:
            target = self.context_window_tokens // 2
            estimated, source = self.estimate_session_prompt_tokens(session)
            if estimated <= 0:
                return
            if estimated < self.context_window_tokens:
                logger.debug(
                    "Token consolidation idle {}: {}/{} via {}",
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                )
                return

            for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
                if estimated <= target:
                    return

                boundary = self.pick_consolidation_boundary(
                    session, max(1, estimated - target)
                )
                if boundary is None:
                    logger.debug(
                        "Token consolidation: no safe boundary for {} (round {})",
                        session.key,
                        round_num,
                    )
                    return

                end_idx = boundary[0]
                chunk = session.messages[session.last_consolidated:end_idx]
                if not chunk:
                    return

                logger.info(
                    "Token consolidation round {} for {}: {}/{} via {}, chunk={} msgs",
                    round_num,
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                    len(chunk),
                )
                if not await self.consolidate_messages(chunk):
                    return
                session.last_consolidated = end_idx
                self.sessions.save(session)

                estimated, source = self.estimate_session_prompt_tokens(session)
                if estimated <= 0:
                    return


__all__ = [
    "BaseMemoryStore",
    "LongTermMemoryStore",
    "MemoryStore",
    "MemoryConsolidator",
    "create_memory_store",
    "create_memory_store_from_config",
    "MEMORY_BACKENDS",
]
