import threading
import time
from pathlib import Path
from typing import List, Dict, Set
import os
import logging

from memory_entry import MemoryEntry
from heap_segment import HeapSegment
from data_segment import DataSegment
from config import DEDUP_SIMILARITY_THRESHOLD

logger = logging.getLogger(__name__)

class Consolidator:
    def __init__(
        self,
        heap_dir: Path,
        data_segment: DataSegment,
        interval: int = 10,
        threshold: int = 5
    ):
        self.heap_dir = Path(heap_dir)
        self.data_segment = data_segment
        self.interval = interval
        self.threshold = threshold
        self._running = False
        self._thread: threading.Thread = None
        self._agent_versions: Dict[str, int] = {}
        self._processed_hashes: Set[str] = set()
        self._merge_count = 0
        self._total_merge_time = 0.0

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Consolidator started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Consolidator stopped")

    def _run_loop(self):
        while self._running:
            time.sleep(self.interval)
            if self._running:
                self.trigger_merge()

    def trigger_merge(self):
        start_time = time.perf_counter()
        logger.info("Triggering merge...")

        try:
            self._merge_all_heaps()
            elapsed = time.perf_counter() - start_time
            self._total_merge_time += elapsed
            self._merge_count += 1
            logger.info(f"Merge completed in {elapsed:.4f}s, data_segment_version={self.data_segment.version}")
        except Exception as e:
            logger.error(f"Merge failed: {e}")

    def _merge_all_heaps(self):
        if not self.heap_dir.exists():
            return

        for heap_file in os.listdir(self.heap_dir):
            if not heap_file.startswith("heap_") or not heap_file.endswith(".jsonl"):
                continue

            agent_id = heap_file.replace("heap_", "").replace(".jsonl", "")
            heap_segment = HeapSegment(agent_id, self.heap_dir)

            last_version = self._agent_versions.get(agent_id, 0)
            new_entries = heap_segment.get_increments(last_version)

            if not new_entries:
                continue

            logger.debug(f"Found {len(new_entries)} new entries for agent {agent_id}")

            for entry in new_entries:
                if self._should_keep(entry):
                    self.data_segment.append(entry)
                    self._processed_hashes.add(entry.get_content_hash())

            self._agent_versions[agent_id] = heap_segment.version

    def _should_keep(self, entry: MemoryEntry) -> bool:
        content_hash = entry.get_content_hash()
        if content_hash in self._processed_hashes:
            logger.debug(f"Duplicate entry filtered: {content_hash}")
            return False

        return True

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def get_stats(self) -> Dict:
        return {
            "merge_count": self._merge_count,
            "total_merge_time": self._total_merge_time,
            "avg_merge_time": self._total_merge_time / self._merge_count if self._merge_count > 0 else 0,
            "agent_versions": self._agent_versions,
            "processed_entries": len(self._processed_hashes),
            "data_segment_version": self.data_segment.version
        }
