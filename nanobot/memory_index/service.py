"""IndexService — lifecycle wrapper around MemoryIndex with optional file watcher."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import MemoryIndexConfig
    from nanobot.memory_index.qmd import QMDSearcher
    from nanobot.memory_index.search import SearchResult


class IndexService:
    """Lifecycle object that owns MemoryIndex and an optional watchdog file observer."""

    def __init__(self, workspace: Path, cfg: MemoryIndexConfig) -> None:
        from nanobot.memory_index.index import MemoryIndex

        self.index = MemoryIndex(workspace, cfg)
        self._cfg = cfg
        self._observer = None
        self._qmd: QMDSearcher | None = None
        if cfg.backend == "qmd":
            from nanobot.memory_index.qmd import QMDSearcher
            self._qmd = QMDSearcher(cfg.qmd_binary)

    async def start(self) -> None:
        """Index memory files at startup; optionally start the file watcher."""
        await self.index.startup_index()
        if self._cfg.watch_files:
            self._start_watcher()

    async def stop(self) -> None:
        """Stop the file watcher if running."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    @property
    def inject_top_k(self) -> int:
        """Number of memory chunks to inject per turn (0 = disabled)."""
        return self._cfg.inject_top_k

    async def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        """Backend-aware search: SQLite with optional QMD re-ranking."""
        k = top_k if top_k is not None else self._cfg.query.top_k
        if self._qmd is not None and self._qmd.is_available():
            candidate_k = min(k * 3, 30)
            candidates = await self.index.search(query, top_k=candidate_k)
            return await self._qmd.rerank(query, candidates, top_k=k)
        return await self.index.search(query, top_k=k)

    def _start_watcher(self) -> None:
        """Start a watchdog observer that re-indexes on MEMORY.md / HISTORY.md changes."""
        import asyncio

        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        loop = asyncio.get_running_loop()
        index = self.index
        memory_dir = self.index.memory_dir

        class _MemoryFileHandler(FileSystemEventHandler):
            def on_modified(self, event) -> None:
                if not event.is_directory:
                    p = Path(event.src_path)
                    if p.name in ("MEMORY.md", "HISTORY.md"):
                        asyncio.run_coroutine_threadsafe(index._index_file(p), loop)

            def on_created(self, event) -> None:
                self.on_modified(event)

        observer = Observer()
        observer.schedule(_MemoryFileHandler(), str(memory_dir), recursive=False)
        observer.start()
        self._observer = observer
        logger.info("Memory file watcher started for {}", memory_dir)
