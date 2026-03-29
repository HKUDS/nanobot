"""IndexService — lifecycle wrapper around MemoryIndex with optional file watcher."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import MemoryIndexConfig


class IndexService:
    """Lifecycle object that owns MemoryIndex and an optional watchdog file observer."""

    def __init__(self, workspace: Path, cfg: MemoryIndexConfig) -> None:
        from nanobot.memory_index.index import MemoryIndex

        self.index = MemoryIndex(workspace, cfg)
        self._cfg = cfg
        self._observer = None

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
