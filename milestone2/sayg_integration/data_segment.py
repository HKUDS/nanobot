import threading
from pathlib import Path
from typing import List
from memory_entry import MemoryEntry

class DataSegment:
    def __init__(self, data_segment_dir: Path):
        self.data_dir = Path(data_segment_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_path = self.data_dir / "data_segment.jsonl"
        self._version = 0
        self._lock = threading.Lock()
        if not self.data_path.exists():
            self.data_path.touch()

    def _get_version(self) -> int:
        if self.data_path.stat().st_size == 0:
            return 0
        with open(self.data_path, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)

    def append(self, entry: MemoryEntry) -> bool:
        with self._lock:
            entry.type = "data"
            entry.metadata["version"] = self._get_version() + 1
            with open(self.data_path, 'a', encoding='utf-8') as f:
                f.write(entry.to_json() + '\n')
            return True

    def read_all(self) -> List[MemoryEntry]:
        if self.data_path.stat().st_size == 0:
            return []

        entries = []
        with open(self.data_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    entries.append(MemoryEntry.from_json(line))
        return entries

    def search(self, query: str, top_k: int = 5) -> List[MemoryEntry]:
        results = []
        keywords = query.lower().split()

        if self.data_path.stat().st_size == 0:
            return results

        with open(self.data_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    entry = MemoryEntry.from_json(line)
                    content_lower = entry.content.lower()
                    if any(kw in content_lower for kw in keywords):
                        results.append(entry)
                        if len(results) >= top_k:
                            break
        return results

    def clear(self) -> None:
        with self._lock:
            if self.data_path.exists():
                self.data_path.unlink()
            self.data_path.touch()
            self._version = 0

    def count(self) -> int:
        return self._get_version()

    @property
    def version(self) -> int:
        return self._get_version()
