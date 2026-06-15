"""Background sync daemon for the subconscious.

Runs as a daemon thread triggered by:
1. Nanobot startup (initial vault ingest)
2. Periodic background re-scan (every SYNC_INTERVAL_S seconds)
3. Dream events (export memory → vault after each dream cycle)

Inspired by OpenHuman's memory_sync and memory_queue subsystems.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from loguru import logger

from nanobot.subconscious.store import SubconsciousStore
from nanobot.subconscious.vault import ObsidianVault

# Re-scan vault every 30 minutes
SYNC_INTERVAL_S = 1800


class SubconsciousDaemon:
    """Coordinates periodic vault sync and memory export."""

    def __init__(
        self,
        vault_path: Path,
        nanobot_workspace: Path,
        db_path: Path | None = None,
    ) -> None:
        self.vault_path = Path(vault_path).expanduser().resolve()
        self.workspace = Path(nanobot_workspace).expanduser().resolve()
        if db_path is None:
            db_path = self.workspace / "subconscious.db"
        self.store = SubconsciousStore(db_path)
        self.vault = ObsidianVault(self.vault_path, self.store)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start daemon thread and initial ingest."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="subconscious-daemon"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.vault.stop_watching()
        if self._thread:
            self._thread.join(timeout=10)

    def wait_ready(self, timeout: float = 30) -> bool:
        """Block until initial ingest completes."""
        return self._ready.wait(timeout=timeout)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        logger.info("Subconscious daemon starting — vault: {}", self.vault_path)

        # Initial full scan
        result = self.vault.scan_and_ingest()
        logger.info("Initial vault ingest: {}", result)

        # Export memory to vault
        self._export_memory()

        # Start file watcher for incremental updates
        self.vault.start_watching()

        self._ready.set()

        # Periodic re-scan loop
        while not self._stop.wait(timeout=SYNC_INTERVAL_S):
            logger.debug("Subconscious: periodic re-scan")
            result = self.vault.scan_and_ingest()
            if result.get("ingested", 0) > 0:
                logger.info("Periodic scan: {}", result)
            self._export_memory()

        logger.info("Subconscious daemon stopped")

    def _export_memory(self) -> None:
        try:
            result = self.vault.export_nanobot_memory(self.workspace)
            if result.get("exported"):
                logger.debug("Exported memory to vault: {}", result["exported"])
        except Exception as exc:
            logger.warning("Memory export failed: {}", exc)

    # ------------------------------------------------------------------
    # On-demand operations (called by the tool)
    # ------------------------------------------------------------------

    def trigger_sync(self, force: bool = False) -> dict:
        """Force an immediate vault sync."""
        result = self.vault.scan_and_ingest(force=force)
        self._export_memory()
        return {**result, "stats": self.store.stats()}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return self.store.search(query, limit=limit)

    def recall(self, limit: int = 20) -> list[dict]:
        return self.store.recall(limit=limit)

    def stats(self) -> dict:
        return self.store.stats()

    def entity_graph(self, limit: int = 30) -> list[dict]:
        return self.vault.entity_graph(limit=limit)
