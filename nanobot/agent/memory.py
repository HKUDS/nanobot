"""Memory system for persistent agent memory."""

import re
from pathlib import Path
from datetime import datetime
from typing import List

from nanobot.utils.helpers import ensure_dir, today_date
from loguru import logger


class MemoryStore:
    """
    Memory system for the agent.
    
    Supports daily notes (memory/YYYY-MM-DD.md) and long-term memory (MEMORY.md).
    """
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
    
    def get_today_file(self) -> Path:
        return self.memory_dir / f"{today_date()}.md"
    
    def read_today(self) -> str:
        today_file = self.get_today_file()
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""
    
    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""
    
    def list_memory_files(self) -> list[Path]:
        if not self.memory_dir.exists():
            return []
        
        files = list(self.memory_dir.glob("????-??-??.md"))
        return sorted(files, reverse=True)
    
    def get_memory_context(self) -> str:
        """
        Get memory context for the agent.
        """
        parts = []
        
        # Long-term memory
        long_term = self.read_long_term()
        if long_term:
            parts.append("## Long-term Memory\n" + long_term)
        
        # Today's notes
        today = self.read_today()
        if today:
            parts.append("## Today's Notes\n" + today)
        
        return "\n\n".join(parts) if parts else ""
    
    def search_daily_memories(
        self, 
        keywords: List[str] | None = None,
        regex_patterns: List[str] | None = None,
        max_results: int = 10
    ) -> str:
        """
        Search through daily memory files for keywords or regex patterns.
        """
        if not keywords and not regex_patterns:
            return ""
        
        daily_files = self._get_daily_memory_files()
        
        if not daily_files:
            return ""
        
        all_results = []
        for file_path in daily_files:
            results = self._grep_file(file_path, keywords or [], regex_patterns)
            for result in results:
                all_results.append({
                    "file": file_path.name,
                    "line": result
                })
                if len(all_results) >= max_results:
                    break
            if len(all_results) >= max_results:
                break
        
        if not all_results:
            return ""
        
        output_parts = []
        for result in all_results:
            output_parts.append(f"[{result['file']}] {result['line']}")
        
        return "\n".join(output_parts)
    
    def _get_daily_memory_files(self) -> List[Path]:
        if not self.memory_dir.exists():
            return []
        
        pattern = re.compile(r'^\d{4}-\d{2}-\d{2}\.md$')
        files = [
            f for f in self.memory_dir.iterdir()
            if f.is_file() and pattern.match(f.name)
        ]
        
        return sorted(files, reverse=True)
    
    def _grep_file(self, file_path: Path, keywords: List[str], 
                   regex_patterns: List[str] | None = None) -> List[str]:
        """
        Search a single file for keywords or regex patterns.
        """
        patterns = []
        
        for keyword in keywords:
            pattern_str = r'\b' + re.escape(keyword) + r'\b'
            try:
                patterns.append(re.compile(pattern_str, re.IGNORECASE))
            except re.error:
                continue
        
        if regex_patterns:
            for regex_pattern in regex_patterns:
                try:
                    re.compile(regex_pattern, re.IGNORECASE)
                    patterns.append(re.compile(regex_pattern, re.IGNORECASE))
                except re.error:
                    continue
        
        if not patterns:
            return []
        
        results = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    for pattern in patterns:
                        try:
                            if pattern.search(line):
                                results.append(line.rstrip())
                                break
                        except Exception:
                            continue
        except Exception:
            logger.error(f"Error reading file: {file_path}")
            return []
        
        return results