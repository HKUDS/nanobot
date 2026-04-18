import time
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from contextlib import contextmanager

class Timer:
    def __init__(self, log_path: Path = None, enabled: bool = True):
        self.log_path = log_path
        self.enabled = enabled
        self.current_operation: Optional[str] = None
        self.operation_start: float = 0
        self.results: Dict[str, Dict[str, Any]] = {}

    @contextmanager
    def measure(self, operation_name: str, metadata: Dict[str, Any] = None):
        if not self.enabled:
            yield
            return

        self.current_operation = operation_name
        self.operation_start = time.perf_counter()
        start_time = datetime.now().isoformat()

        try:
            yield
        finally:
            elapsed = time.perf_counter() - self.operation_start
            end_time = datetime.now().isoformat()

            result = {
                "operation": operation_name,
                "start_time": start_time,
                "end_time": end_time,
                "elapsed_seconds": round(elapsed, 6),
                "metadata": metadata or {}
            }

            self.results[operation_name] = result

            if self.log_path:
                with open(self.log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(result, ensure_ascii=False) + '\n')

            self.current_operation = None
            self.operation_start = 0

    def record(self, operation_name: str, elapsed_seconds: float, metadata: Dict[str, Any] = None):
        if not self.enabled:
            return

        result = {
            "operation": operation_name,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }

        self.results[operation_name] = result

        if self.log_path:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(result, ensure_ascii=False) + '\n')

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_operations": len(self.results),
            "operations": self.results
        }

    def clear(self):
        self.results.clear()
