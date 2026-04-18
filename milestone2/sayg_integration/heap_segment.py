import threading
import os
from pathlib import Path
from typing import List
from memory_entry import MemoryEntry

class HeapSegment:
    def __init__(self, agent_id: str, heap_dir: Path):
        self.agent_id = agent_id
        self.heap_dir = Path(heap_dir)
        self.heap_dir.mkdir(parents=True, exist_ok=True)
        self.heap_path = self.heap_dir / f"heap_{agent_id}.jsonl"
        self._version = 0
        self._lock = threading.Lock()
        self._init_file()

    def _init_file(self):
        if not self.heap_path.exists():
            self.heap_path.touch()

    def _get_version(self) -> int:
        if not self.heap_path.exists() or self.heap_path.stat().st_size == 0:
            return 0
        with open(self.heap_path, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)

    def append(self, entry: MemoryEntry) -> bool:
        with self._lock:
            self._version = self._get_version() + 1
            entry.metadata["version"] = self._version
            entry.metadata["agent_id"] = self.agent_id

            with open(self.heap_path, 'a', encoding='utf-8') as f:
                f.write(entry.to_json() + '\n')

        return True

    def read_all(self) -> List[MemoryEntry]:
        if not self.heap_path.exists() or self.heap_path.stat().st_size == 0:
            return []

        entries = []
        with open(self.heap_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    entries.append(MemoryEntry.from_json(line))
        return entries

    def get_increments(self, last_version: int) -> List[MemoryEntry]:
        all_entries = self.read_all()
        return [e for e in all_entries if e.metadata.get("version", 0) > last_version]

    def clear(self) -> None:
        with self._lock:
            if self.heap_path.exists():
                self.heap_path.unlink()
            self.heap_path.touch()
            self._version = 0

    def count(self) -> int:
        return self._get_version()

    @property
    def version(self) -> int:
        return self._get_version()
