"""OpenViking context database adapter (optional dependency).

Provides a VikingContextProvider that wraps AsyncOpenViking for use by
ContextBuilder and agent tools.  If ``openviking`` is not installed the
module still imports cleanly — callers check ``HAS_VIKING`` at runtime.

Install with:  pip install nanobot-ai[viking]
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import VikingConfig

try:
    from openviking import AsyncOpenViking

    HAS_VIKING = True
except ImportError:
    HAS_VIKING = False
    AsyncOpenViking = None  # type: ignore[assignment,misc]


class VikingContextProvider:
    """Thin adapter between nanobot and the OpenViking embedded client.

    Public surface is intentionally minimal so the rest of nanobot only
    depends on this class, never on ``openviking`` directly.
    """

    def __init__(self, config: VikingConfig) -> None:
        self._config = config
        self._ov: Any = None  # AsyncOpenViking instance (set in initialize)
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Start the embedded OpenViking storage & index services."""
        if not HAS_VIKING:
            logger.warning("openviking package not installed — VikingContextProvider disabled")
            return

        # Point OpenViking at the user-specified config, if any.
        if self._config.config_path:
            os.environ.setdefault("OPENVIKING_CONFIG_FILE", self._config.config_path)

        try:
            self._ov = AsyncOpenViking()
            await self._ov.initialize()
            self._initialized = True
            logger.info("OpenViking initialized successfully")
        except Exception:
            logger.exception("Failed to initialize OpenViking — falling back to default memory")
            self._ov = None

    async def close(self) -> None:
        """Release OpenViking resources."""
        if self._ov is not None:
            try:
                await self._ov.close()
            except Exception:
                logger.exception("Error closing OpenViking")
            finally:
                self._ov = None
                self._initialized = False

    @property
    def is_ready(self) -> bool:
        return self._initialized and self._ov is not None

    # ------------------------------------------------------------------
    # Memory context (compatible with MemoryStore.get_memory_context)
    # ------------------------------------------------------------------

    def get_memory_context(self) -> str:
        """Return memory context string for inclusion in the system prompt.

        Falls back to empty string if Viking is unavailable so that
        ``ContextBuilder`` can always call this safely.
        """
        if not self.is_ready:
            return ""
        try:
            # Run the async search in a sync wrapper — ContextBuilder.build_system_prompt is sync.
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're already inside an async context — schedule a coroutine.
                # Return empty for now; the real memory will be injected via
                # search_context() in the async tool path.
                return ""
            return loop.run_until_complete(self._fetch_memory_summary())
        except Exception:
            logger.exception("Viking get_memory_context failed")
            return ""

    async def _fetch_memory_summary(self) -> str:
        """Retrieve user + agent memory overview from Viking."""
        parts: list[str] = []
        try:
            for uri in ("viking://user/", "viking://agent/"):
                overview = await self._ov.overview(uri)
                if overview:
                    parts.append(str(overview))
        except Exception:
            logger.debug("Viking memory overview unavailable")
        return "\n\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Semantic search
    # ------------------------------------------------------------------

    async def search_context(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 5,
    ) -> str:
        """Run a semantic search across Viking resources and return formatted results."""
        if not self.is_ready:
            return "OpenViking is not available."
        try:
            results = await self._ov.search(
                query=query,
                session=session_id,
                limit=limit,
            )
            if not results:
                return "No results found."
            return str(results)
        except Exception as exc:
            logger.exception("Viking search failed")
            return f"Search error: {exc}"

    # ------------------------------------------------------------------
    # Resource management
    # ------------------------------------------------------------------

    async def add_resource(
        self,
        path: str,
        build_index: bool = True,
        summarize: bool = True,
    ) -> str:
        """Add a file or URL as a Viking resource."""
        if not self.is_ready:
            return "OpenViking is not available."
        try:
            await self._ov.add_resource(
                path,
                build_index=build_index,
                summarize=summarize,
                wait=True,
                timeout=120,
            )
            return f"Resource added: {path}"
        except Exception as exc:
            logger.exception("Viking add_resource failed")
            return f"Error adding resource: {exc}"

    # ------------------------------------------------------------------
    # Session commit (extract memories from conversation)
    # ------------------------------------------------------------------

    async def commit_session(self, session_id: str) -> str:
        """Commit a Viking session to extract long-term memories."""
        if not self.is_ready:
            return "OpenViking is not available."
        try:
            await self._ov.commit_session(session_id)
            return f"Session '{session_id}' committed."
        except Exception as exc:
            logger.exception("Viking commit_session failed")
            return f"Error committing session: {exc}"
