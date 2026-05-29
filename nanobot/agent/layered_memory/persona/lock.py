"""File lock for ``USER.md`` single-writer (L3 vs Dream)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from filelock import FileLock, Timeout
from loguru import logger

from nanobot.utils.helpers import ensure_dir

_LOCK_NAME = "persona.lock"


class PersonaLock:
    """Cross-process lock at ``{workspace}/.nanobot/persona.lock``."""

    __slots__ = ("_lock", "_path", "_timeout")

    def __init__(self, workspace: Path, *, timeout_seconds: float = 30.0) -> None:
        self._path = ensure_dir(workspace / ".nanobot") / _LOCK_NAME
        self._timeout = timeout_seconds
        self._lock = FileLock(str(self._path), timeout=-1)

    @property
    def lock_path(self) -> Path:
        return self._path

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Acquire lock or raise ``Timeout``."""
        try:
            self._lock.acquire(timeout=self._timeout)
        except Timeout as exc:
            logger.warning("layered_memory persona_lock_timeout path={}", self._path)
            raise Timeout(
                f"persona lock timeout after {self._timeout}s: {self._path}"
            ) from exc
        try:
            yield
        finally:
            self._lock.release()
