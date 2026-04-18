import threading
import json
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from memory_entry import MemoryEntry

class PublicMemory:
    def __init__(self, public_memory_path: Path):
        self.path = Path(public_memory_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        self._lock = threading.Lock()
        self._version = 0
        self._load_version()

    def _load_version(self):
        if self.path.stat().st_size == 0:
            self._version = 0
            return
        with open(self.path, 'r', encoding='utf-8') as f:
            self._version = sum(1 for _ in f)

    def append(self, entry: MemoryEntry) -> bool:
        with self._lock:
            self._version += 1
            entry.metadata["version"] = self._version
            entry.metadata["type"] = "public"

            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(entry.to_json() + '\n')

        return True

    def read_all(self) -> List[MemoryEntry]:
        if self.path.stat().st_size == 0:
            return []

        entries = []
        with open(self.path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    entries.append(MemoryEntry.from_json(line))
        return entries

    def get_increments(self, last_version: int) -> List[MemoryEntry]:
        all_entries = self.read_all()
        return [e for e in all_entries if e.metadata.get("version", 0) > last_version]

    def search(self, query: str, top_k: int = 5) -> List[MemoryEntry]:
        results = []
        keywords = query.lower().split()

        if self.path.stat().st_size == 0:
            return results

        with open(self.path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    entry = MemoryEntry.from_json(line)
                    content_lower = entry.content.lower()
                    if any(kw in content_lower for kw in keywords):
                        results.append(entry)
                        if len(results) >= top_k:
                            break
        return results

    def get_by_page_id(self, page_id: str) -> Optional[MemoryEntry]:
        all_entries = self.read_all()
        for entry in all_entries:
            if entry.metadata.get("page_id") == page_id:
                return entry
        return None

    def get_by_task_id(self, task_id: str) -> List[MemoryEntry]:
        results = []
        all_entries = self.read_all()
        for entry in all_entries:
            if entry.metadata.get("task_id") == task_id:
                results.append(entry)
        return results

    def count(self) -> int:
        return self._version

    @property
    def version(self) -> int:
        return self._version

    def clear(self) -> None:
        with self._lock:
            if self.path.exists():
                self.path.unlink()
            self.path.touch()
            self._version = 0

    def get_stats(self) -> Dict:
        entries = self.read_all()
        return {
            "total_entries": len(entries),
            "latest_version": self._version,
            "unique_pages": len(set(e.metadata.get("page_id") for e in entries if e.metadata.get("page_id"))),
            "unique_agents": len(set(e.agent_id for e in entries))
        }
