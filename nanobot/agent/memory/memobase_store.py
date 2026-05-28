"""Memobase memory store adapter.

Wraps the ``memobase`` SDK to provide **user-profile-based long-term memory**.
Instead of vector-similarity search, Memobase extracts and maintains a
structured user profile (name, interests, work, psychology…) plus an event
timeline.  The key advantage is near-zero online latency: the profile is
always ready — no embedding computation on hot path.

Architecture:
- Memobase runs as a separate service (FastAPI + Postgres + Redis).
- This adapter talks to it via the async HTTP SDK.
- Each ``user_id`` maps to a Memobase user; profiles accumulate over time.

Install::

    pip install memobase

Start the server::

    # Local Docker (default token = "secret")
    docker run -p 8019:8019 memodb/memobase:latest

    # Or use Memobase Cloud: https://app.memobase.io

Reference: https://github.com/memodb-io/memobase
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Stable namespace for deterministic UUID generation from logical user IDs.
_UUID_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # URL namespace


def _to_uuid(user_id: str) -> str:
    """Convert an arbitrary user_id string to a deterministic UUID v5.

    Memobase requires UUID-format user IDs.  ``uuid5`` is deterministic:
    the same ``user_id`` string always produces the same UUID, so no
    external mapping table is needed.
    """
    return str(uuid.uuid5(_UUID_NS, user_id))

from loguru import logger

from nanobot.agent.memory.base import BaseMemoryStore

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


# ── lazy import ───────────────────────────────────────────────────────────────

def _lazy_import_memobase():
    try:
        from memobase.core.async_entry import AsyncMemoBaseClient
        from memobase.core.blob import Blob
        return AsyncMemoBaseClient, Blob
    except ImportError:
        raise ImportError(
            "memobase is required for MemobaseMemoryStore. "
            "Install it with: pip install memobase\n"
            "Start the server: docker run -p 8019:8019 memodb/memobase:latest\n"
            "Reference: https://github.com/memodb-io/memobase"
        )


# ── store ─────────────────────────────────────────────────────────────────────

class MemobaseMemoryStore(BaseMemoryStore):
    """Memory store backed by Memobase — user-profile long-term memory.

    Memobase builds and maintains a **structured user profile** from
    conversations: name, interests, work history, psychology, demographics,
    etc.  Retrieval is based on this profile, not vector search, giving
    sub-100 ms latency for profile reads.

    It also records an event timeline that can be searched for temporal
    queries like "what did the user say about X last week?"

    Configuration (in ``~/.nanobot/config.json``)::

        "memobase": {
            "enabled": true,
            "projectUrl": "http://localhost:8019",
            "apiKey": "secret",
            "maxTokenSize": 500
        }

    Start the Memobase server::

        docker run -p 8019:8019 memodb/memobase:latest
        # Default project token: "secret"

    Or sign up for Memobase Cloud at https://app.memobase.io for a managed
    instance with a free tier.
    """

    def __init__(
        self,
        workspace: Path,
        *,
        project_url: str = "http://localhost:8019",
        api_key: str = "secret",
        max_token_size: int = 500,
        **kwargs: Any,
    ):
        super().__init__(workspace)
        self._project_url = project_url
        self._api_key = api_key
        self._max_token_size = max_token_size
        self._client: Any = None
        self._users: dict[str, Any] = {}

        # Persistent event loop for all Memobase async operations.
        # httpx.AsyncClient binds its connection pool to the event loop
        # active at request time; a single dedicated loop avoids
        # "Event loop is closed" errors from sync→async bridging.
        self._dedicated_loop = asyncio.new_event_loop()
        self._dedicated_thread = threading.Thread(
            target=self._dedicated_loop.run_forever,
            daemon=True,
            name="memobase-loop",
        )
        self._dedicated_thread.start()
        logger.info(
            "MemobaseMemoryStore initialized (url={}, workspace={})",
            project_url,
            workspace,
        )

    # ── dedicated-loop helpers ────────────────────────────────────────────────

    def _ensure_client(self) -> None:
        """Lazily create the async client on the dedicated loop."""
        if self._client is not None:
            return
        AsyncMemoBaseClient, _ = _lazy_import_memobase()
        self._client = AsyncMemoBaseClient(
            project_url=self._project_url,
            api_key=self._api_key,
        )

    def _run_sync(self, coro: Any, timeout: float = 60) -> Any:
        """Run *coro* on the dedicated loop, blocking the calling thread."""
        self._ensure_client()
        future = asyncio.run_coroutine_threadsafe(coro, self._dedicated_loop)
        return future.result(timeout=timeout)

    async def _run_on_dedicated(self, coro: Any) -> Any:
        """Schedule *coro* on the dedicated loop and ``await`` it from any loop."""
        self._ensure_client()
        future = asyncio.run_coroutine_threadsafe(coro, self._dedicated_loop)
        return await asyncio.wrap_future(future)

    # ── internal ─────────────────────────────────────────────────────────────

    async def _get_user(self, user_id: str) -> Any:
        """Get or create a Memobase user handle for *user_id*.

        Memobase requires UUID-format IDs.  We convert the logical ``user_id``
        to a deterministic UUID v5, then call ``get_or_create_user``.

        The SDK's ``get_or_create_user`` catches ``ServerError`` (404), but the
        local Memobase server raises ``httpx.HTTPStatusError`` (422) for
        unknown UUIDs, so we fall back to explicit ``add_user`` + ``get_user``
        when needed.
        """
        if user_id in self._users:
            return self._users[user_id]

        memobase_id = _to_uuid(user_id)
        try:
            user = await self._client.get_or_create_user(memobase_id)
        except Exception:
            # get_or_create_user may not catch httpx.HTTPStatusError on local
            # deployments — explicitly create the user and retrieve the handle.
            try:
                await self._client.add_user(data={"nanobot_user_id": user_id}, id=memobase_id)
            except Exception:
                pass  # already exists or creation failed — proceed to get_user
            user = await self._client.get_user(memobase_id)

        self._users[user_id] = user
        return user

    # ── CRUD (internal, runs on dedicated loop) ────────────────────────────────

    async def _add_impl(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
        sync: bool = False,
    ) -> Any:
        _, Blob = _lazy_import_memobase()
        valid = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") in ("user", "assistant") and m.get("content") and isinstance(m.get("content"), str)
        ]
        if not valid:
            return {}
        try:
            from memobase.core.blob import ChatBlob
        except ImportError:
            from memobase import ChatBlob  # type: ignore[no-redef]

        u = await self._get_user(user_id)
        blob_id = await u.insert(ChatBlob(messages=valid), sync=sync)
        logger.debug("Memobase inserted blob={} for user={} (sync={})", blob_id, user_id, sync)
        return {"blob_id": blob_id}

    async def _search_impl(
        self, query: str, user_id: str = "default", limit: int = 5
    ) -> list[dict[str, Any]]:
        u = await self._get_user(user_id)
        events = await u.search_event(query=query, topk=limit)
        result = [
            {
                "id": str(getattr(e, "event_id", getattr(e, "id", ""))),
                "memory": getattr(e, "event_tip", getattr(e, "event_data", str(e))),
                "created_at": str(getattr(e, "created_at", "")),
            }
            for e in events
        ]
        logger.info("MemobaseMemoryStore search result={}", result)
        return result

    async def _get_all_impl(self, user_id: str = "default") -> list[dict[str, Any]]:
        u = await self._get_user(user_id)
        profiles = await u.profile(max_token_size=4096)
        return [
            {
                "id": str(getattr(p, "id", "")),
                "memory": getattr(p, "describe", str(p)),
                "topic": getattr(p, "topic", ""),
                "sub_topic": getattr(p, "sub_topic", ""),
                "content": getattr(p, "content", ""),
            }
            for p in profiles
        ]

    async def _get_context_impl(self, user_id: str, max_token_size: int) -> str:
        u = await self._get_user(user_id)
        ctx = await u.context(max_token_size=max_token_size)
        return ctx if ctx else ""

    # ── CRUD (public, routes to dedicated loop) ──────────────────────────────

    async def add(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
        **kwargs: Any,
    ) -> Any:
        """Insert a chat blob and flush it into the user profile."""
        try:
            return await self._run_on_dedicated(
                self._add_impl(messages, user_id, sync=kwargs.get("sync", False))
            )
        except Exception:
            logger.exception("Memobase add failed for user={}", user_id)
            raise

    async def search(
        self,
        query: str,
        user_id: str = "default",
        limit: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search the user's event timeline for entries matching *query*."""
        try:
            return await self._run_on_dedicated(self._search_impl(query, user_id, limit))
        except Exception:
            logger.exception("Memobase search failed for user={}", user_id)
            return []

    async def get_all(
        self,
        user_id: str = "default",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Retrieve all profile entries for the user."""
        try:
            return await self._run_on_dedicated(self._get_all_impl(user_id))
        except Exception:
            logger.exception("Memobase get_all failed for user={}", user_id)
            return []

    async def update(self, memory_id: str, content: str, **kwargs: Any) -> bool:
        """Update a specific profile entry."""
        user_id = kwargs.get("user_id", "default")
        try:
            async def _impl():
                u = await self._get_user(user_id)
                await u.update_profile(
                    profile_id=memory_id, content=content,
                    topic=kwargs.get("topic", "general"),
                    sub_topic=kwargs.get("sub_topic", "note"),
                )
                return True
            return await self._run_on_dedicated(_impl())
        except Exception:
            logger.exception("Memobase update failed for memory_id={}", memory_id)
            return False

    async def delete(self, memory_id: str, **kwargs: Any) -> bool:
        """Delete a specific profile entry."""
        user_id = kwargs.get("user_id", "default")
        try:
            async def _impl():
                u = await self._get_user(user_id)
                await u.delete_profile(memory_id)
                return True
            return await self._run_on_dedicated(_impl())
        except Exception:
            logger.exception("Memobase delete failed for memory_id={}", memory_id)
            return False

    # ── Agent prompt integration ──────────────────────────────────────────────

    def get_memory_context(self, **kwargs: Any) -> str:
        """Return a formatted user profile string for injection into the agent prompt.

        Uses the dedicated loop directly (blocking) — safe to call from
        any thread or from within a running event loop.
        """
        user_id = kwargs.get("user_id", "default")
        max_tokens = kwargs.get("max_token_size", self._max_token_size)
        try:
            return self._run_sync(self._get_context_impl(user_id, max_tokens))
        except Exception:
            logger.exception("Memobase get_memory_context failed")
            return ""

    # ── Consolidation ─────────────────────────────────────────────────────────

    async def consolidate(
        self,
        messages: list[dict[str, Any]],
        provider: LLMProvider,
        model: str,
        user_id: str = "default",
    ) -> bool:
        """Consolidate messages by inserting them into Memobase."""
        if not messages:
            return True
        try:
            await self.add(messages, user_id=user_id, sync=False)
            self._consecutive_failures = 0
            logger.info("Memobase consolidation done for {} messages", len(messages))
            return True
        except Exception:
            logger.exception("Memobase consolidation failed")
            return self._fail_or_raw_archive(messages)

    async def flush(self, user_id: str = "default", sync: bool = True) -> bool:
        """Manually flush the buffer to process pending chat blobs."""
        try:
            async def _impl():
                u = await self._get_user(user_id)
                return await u.flush(sync=sync)
            return await self._run_on_dedicated(_impl())
        except Exception:
            logger.exception("Memobase flush failed for user={}", user_id)
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client and stop the dedicated loop."""
        try:
            if self._client:
                await self._run_on_dedicated(self._client.close())
        except Exception:
            pass
        self._dedicated_loop.call_soon_threadsafe(self._dedicated_loop.stop)


if __name__ == "__main__":
    from nanobot.agent.memory import create_memory_store_from_config
    from nanobot.config.loader import load_config

    _config = load_config()
    _store = create_memory_store_from_config(_config.memory, _config.workspace_path)

    _messages = [
        {"role": "user", "content": "我叫王芳，我是一名数据分析师，喜欢爬山"},
        {"role": "assistant", "content": "你好王芳！爬山是个很好的爱好。"},
        {"role": "user", "content": "我在北京工作，最近在学习机器学习"},
    ]

    async def _main():
        await _store.add(_messages, user_id="test_user", sync=True)
        all_profiles = await _store.get_all(user_id="test_user")
        logger.info(all_profiles)
        print("\n=== Profile Entries ===")
        for p in all_profiles:
            print(f"  [{p.get('topic','')}/{p.get('sub_topic','')}] {p.get('content','')}")
        await _store.search(query="王芳的职业", user_id="test_user", sync=True)

    asyncio.run(_main())
