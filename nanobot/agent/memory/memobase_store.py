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
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
        AsyncMemoBaseClient, _ = _lazy_import_memobase()
        self._client: Any = AsyncMemoBaseClient(
            project_url=project_url,
            api_key=api_key,
        )
        self._max_token_size = max_token_size
        # Cache user handles: user_id → AsyncUser
        self._users: dict[str, Any] = {}
        logger.info(
            "MemobaseMemoryStore initialized (url={}, workspace={})",
            project_url,
            workspace,
        )

    # ── internal ─────────────────────────────────────────────────────────────

    async def _get_user(self, user_id: str) -> Any:
        """Get or create a Memobase user handle for *user_id*."""
        if user_id not in self._users:
            self._users[user_id] = await self._client.get_or_create_user(user_id)
        return self._users[user_id]

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def add(
        self,
        messages: list[dict[str, Any]],
        user_id: str = "default",
        **kwargs: Any,
    ) -> Any:
        """Insert a chat blob and flush it into the user profile.

        Memobase will extract profile facts and events from the messages
        asynchronously.  Pass ``sync=True`` as a kwarg to block until
        processing is complete.
        """
        _, Blob = _lazy_import_memobase()

        # Filter to valid message dicts
        valid = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") and m.get("content")
        ]
        if not valid:
            return {}

        try:
            # Import ChatBlob — the concrete Blob subclass for chat messages
            from memobase.core.blob import ChatBlob
        except ImportError:
            # Fallback: try the top-level import
            from memobase import ChatBlob  # type: ignore[no-redef]

        try:
            u = await self._get_user(user_id)
            sync = kwargs.get("sync", False)
            blob_id = await u.insert(ChatBlob(messages=valid), sync=sync)
            logger.debug(
                "Memobase inserted blob={} for user={} (sync={})",
                blob_id, user_id, sync,
            )
            return {"blob_id": blob_id}
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
            u = await self._get_user(user_id)
            events = await u.search_event(query=query, topk=limit)
            return [
                {
                    "id": str(getattr(e, "event_id", getattr(e, "id", ""))),
                    "memory": getattr(e, "event_tip", getattr(e, "event_data", str(e))),
                    "created_at": str(getattr(e, "created_at", "")),
                }
                for e in events
            ]
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
        except Exception:
            logger.exception("Memobase get_all failed for user={}", user_id)
            return []

    async def update(self, memory_id: str, content: str, **kwargs: Any) -> bool:
        """Update a specific profile entry."""
        user_id = kwargs.get("user_id", "default")
        try:
            u = await self._get_user(user_id)
            await u.update_profile(
                profile_id=memory_id,
                content=content,
                topic=kwargs.get("topic", "general"),
                sub_topic=kwargs.get("sub_topic", "note"),
            )
            return True
        except Exception:
            logger.exception("Memobase update failed for memory_id={}", memory_id)
            return False

    async def delete(self, memory_id: str, **kwargs: Any) -> bool:
        """Delete a specific profile entry."""
        user_id = kwargs.get("user_id", "default")
        try:
            u = await self._get_user(user_id)
            await u.delete_profile(memory_id)
            return True
        except Exception:
            logger.exception("Memobase delete failed for memory_id={}", memory_id)
            return False

    # ── Agent prompt integration ──────────────────────────────────────────────

    def get_memory_context(self, **kwargs: Any) -> str:
        """Return a formatted user profile string for injection into the agent prompt."""
        user_id = kwargs.get("user_id", "default")
        max_tokens = kwargs.get("max_token_size", self._max_token_size)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    fut = pool.submit(asyncio.run, self._get_context(user_id, max_tokens))
                    return fut.result(timeout=30)
            else:
                return loop.run_until_complete(self._get_context(user_id, max_tokens))
        except Exception:
            logger.exception("Memobase get_memory_context failed")
            return ""

    async def _get_context(self, user_id: str, max_token_size: int) -> str:
        u = await self._get_user(user_id)
        ctx = await u.context(max_token_size=max_token_size)
        return ctx if ctx else ""

    # ── Consolidation ─────────────────────────────────────────────────────────

    async def consolidate(
        self,
        messages: list[dict[str, Any]],
        provider: LLMProvider,
        model: str,
    ) -> bool:
        """Consolidate messages by inserting them into Memobase."""
        if not messages:
            return True
        try:
            await self.add(messages, sync=False)
            self._consecutive_failures = 0
            logger.info("Memobase consolidation done for {} messages", len(messages))
            return True
        except Exception:
            logger.exception("Memobase consolidation failed")
            return self._fail_or_raw_archive(messages)

    async def flush(self, user_id: str = "default", sync: bool = True) -> bool:
        """Manually flush the buffer to process pending chat blobs.

        Memobase auto-flushes when the buffer exceeds ~1024 tokens or after an
        idle period, but you can call this explicitly at the end of a session.
        """
        try:
            u = await self._get_user(user_id)
            return await u.flush(sync=sync)
        except Exception:
            logger.exception("Memobase flush failed for user={}", user_id)
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        try:
            await self._client.close()
        except Exception:
            pass


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
        ctx = await _store._get_context("test_user", 500)
        print("=== Memobase Context ===")
        print(ctx)
        all_profiles = await _store.get_all(user_id="test_user")
        print("\n=== Profile Entries ===")
        for p in all_profiles:
            print(f"  [{p.get('topic','')}/{p.get('sub_topic','')}] {p.get('content','')}")

    asyncio.run(_main())
