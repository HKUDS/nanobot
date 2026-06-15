"""Obsidian vault integration for nanobot's subconscious.

Handles:
- Scanning the vault and ingesting notes into SubconsciousStore
- Watching for file changes (via watchdog)
- Exporting nanobot memories back to the vault under _nanobot/ folder
- Generating summary nodes mirroring the vault hierarchy
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from loguru import logger

from nanobot.subconscious.store import SubconsciousStore

# Folder inside the vault where nanobot exports its memory
NANOBOT_EXPORT_DIR = "_nanobot"
# Files/dirs to skip during scan
SKIP_PATTERNS = {
    ".obsidian", ".trash", ".git", NANOBOT_EXPORT_DIR,
    "__pycache__", "node_modules", "_deprecated",
}


class ObsidianVault:
    """Manages the bidirectional sync between nanobot and an Obsidian vault."""

    def __init__(self, vault_path: Path, store: SubconsciousStore) -> None:
        self.vault_path = Path(vault_path).expanduser().resolve()
        self.store = store
        self._watcher_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Scanning & Ingestion
    # ------------------------------------------------------------------

    def scan_and_ingest(self, force: bool = False, progress_cb: Callable[[str], None] | None = None) -> dict:
        """Walk the vault and ingest new/modified notes.

        Args:
            force: Re-ingest all files even if unchanged.
            progress_cb: Optional callback(rel_path) called per ingested file.

        Returns:
            Summary dict with counts.
        """
        if not self.vault_path.exists():
            return {"error": f"Vault not found: {self.vault_path}"}

        ingested = 0
        skipped = 0
        errors = 0

        for md_path in self._iter_markdown_files():
            rel = str(md_path.relative_to(self.vault_path))
            mtime = md_path.stat().st_mtime

            if not force and not self.store.needs_ingest(rel, mtime):
                skipped += 1
                continue

            try:
                content = md_path.read_text(encoding="utf-8", errors="ignore")
                chunks = self.store.ingest_document(rel, content, mtime)
                ingested += 1
                if progress_cb:
                    progress_cb(rel)
                logger.debug("Ingested {} -> {} chunks", rel, chunks)
            except Exception as exc:
                logger.warning("Failed to ingest {}: {}", rel, exc)
                errors += 1

        # Remove chunks for deleted files
        known = {m["source_path"] for m in self.store.list_files()}
        current = {
            str(p.relative_to(self.vault_path))
            for p in self._iter_markdown_files()
        }
        for removed in known - current:
            self.store.remove_document(removed)
            logger.debug("Removed stale index for: {}", removed)

        return {"ingested": ingested, "skipped": skipped, "errors": errors}

    def _iter_markdown_files(self):
        """Yield all .md files under vault, skipping ignored directories."""
        for root, dirs, files in os.walk(self.vault_path):
            # Prune skipped dirs in-place
            dirs[:] = [d for d in dirs if d not in SKIP_PATTERNS and not d.startswith(".")]
            for fname in files:
                if fname.endswith(".md"):
                    yield Path(root) / fname

    # ------------------------------------------------------------------
    # Export: nanobot → vault
    # ------------------------------------------------------------------

    def export_nanobot_memory(self, nanobot_dir: Path) -> dict:
        """Copy nanobot's memory files (MEMORY.md, USER.md, SOUL.md) into vault.

        Destination: <vault>/_nanobot/
        """
        dest = self.vault_path / NANOBOT_EXPORT_DIR
        dest.mkdir(exist_ok=True)

        exported = []
        for fname in ("MEMORY.md", "USER.md", "SOUL.md"):
            src = nanobot_dir / fname
            if src.exists():
                shutil.copy2(src, dest / fname)
                exported.append(fname)

        # Also copy history summary if present
        history_summary = nanobot_dir / "memory" / "MEMORY.md"
        if history_summary.exists():
            shutil.copy2(history_summary, dest / "MEMORY.md")
            if "MEMORY.md" not in exported:
                exported.append("MEMORY.md")

        # Write an index note
        index_content = self._build_index_note(exported)
        (dest / "README.md").write_text(index_content, encoding="utf-8")

        return {"exported": exported, "destination": str(dest)}

    def _build_index_note(self, exported_files: list[str]) -> str:
        stats = self.store.stats()
        now = time.strftime("%Y-%m-%d %H:%M")
        lines = [
            "# Nanobot Memory",
            "",
            f"> Auto-generated by nanobot subconscious — last sync: {now}",
            "",
            "## Memory Files",
            "",
        ]
        for f in exported_files:
            lines.append(f"- [[{f}]]")
        lines += [
            "",
            "## Vault Index Stats",
            "",
            f"- **Notes indexed**: {stats['total_files']}",
            f"- **Memory chunks**: {stats['total_chunks']}",
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # File Watcher
    # ------------------------------------------------------------------

    def start_watching(self, debounce_s: float = 2.0) -> None:
        """Start background thread that watches vault for changes."""
        if self._watcher_thread and self._watcher_thread.is_alive():
            return

        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.warning("watchdog not installed — vault watching disabled. Run: pip install watchdog")
            return

        store = self.store
        vault_path = self.vault_path
        pending: dict[str, float] = {}
        lock = threading.Lock()

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if not event.is_directory and event.src_path.endswith(".md"):
                    with lock:
                        pending[event.src_path] = time.time()

            def on_created(self, event):
                self.on_modified(event)

            def on_deleted(self, event):
                if not event.is_directory and event.src_path.endswith(".md"):
                    rel = str(Path(event.src_path).relative_to(vault_path))
                    store.remove_document(rel)
                    logger.info("Vault: removed index for deleted {}", rel)

        observer = Observer()
        observer.schedule(_Handler(), str(vault_path), recursive=True)
        observer.start()

        stop_event = self._stop_event

        def _flush_loop():
            while not stop_event.is_set():
                now = time.time()
                to_process = []
                with lock:
                    for path, ts in list(pending.items()):
                        if now - ts >= debounce_s:
                            to_process.append(path)
                            del pending[path]
                for abs_path in to_process:
                    p = Path(abs_path)
                    if not p.exists():
                        continue
                    rel = str(p.relative_to(vault_path))
                    # Skip nanobot's own export directory
                    if rel.startswith(NANOBOT_EXPORT_DIR):
                        continue
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        mtime = p.stat().st_mtime
                        chunks = store.ingest_document(rel, content, mtime)
                        logger.info("Vault: re-ingested {} -> {} chunks", rel, chunks)
                    except Exception as exc:
                        logger.warning("Vault watch ingest error {}: {}", rel, exc)
                stop_event.wait(timeout=0.5)
            observer.stop()
            observer.join()

        self._stop_event.clear()
        self._watcher_thread = threading.Thread(target=_flush_loop, daemon=True, name="vault-watcher")
        self._watcher_thread.start()
        logger.info("Vault watcher started for: {}", vault_path)

    def stop_watching(self) -> None:
        self._stop_event.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=5)
            self._watcher_thread = None

    # ------------------------------------------------------------------
    # Entity Graph
    # ------------------------------------------------------------------

    def entity_graph(self, limit: int = 50) -> list[dict]:
        """Return top entity → source_path relationships for knowledge graph."""
        db = self.store._db()
        rows = db.execute(
            """SELECT entities, source_path FROM chunks
               ORDER BY mtime DESC LIMIT 500"""
        ).fetchall()

        import json
        graph: dict[str, set[str]] = {}
        for row in rows:
            ents = json.loads(row["entities"])
            src = row["source_path"]
            for e in ents:
                graph.setdefault(e, set()).add(src)

        # Sort by connection count
        sorted_ents = sorted(graph.items(), key=lambda x: len(x[1]), reverse=True)[:limit]
        return [
            {"entity": e, "mentions_in": sorted(list(paths)), "count": len(paths)}
            for e, paths in sorted_ents
        ]
