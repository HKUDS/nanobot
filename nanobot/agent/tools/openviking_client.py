"""VikingClient: thin async wrapper around the AsyncOpenViking singleton."""
from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

_client = None
_init_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


async def get_client(data_path: str):
    """Return the initialized AsyncOpenViking singleton, creating it if needed."""
    global _client
    if _client is not None:
        return _client
    async with _lock():
        if _client is not None:
            return _client
        from openviking import AsyncOpenViking  # type: ignore[import]
        path = str(Path(data_path).expanduser())
        _client = AsyncOpenViking(path=path)
        await _client.initialize()
        logger.info("OpenViking initialized at {}", path)
    return _client
