"""Memory search tool for retrieving relevant historical conversations."""

import re
from pathlib import Path
from typing import Any, List

from loguru import logger

from nanobot.agent.tools.base import Tool


class MemorySearchTool(Tool):
    """
    Tool to search through daily memory files (YYYY-MM-DD.md) using keywords.
    """
    
    def __init__(self, memory_dir: Path):
        self._memory_dir = memory_dir
    
    @property
    def name(self) -> str:
        return "memory_search"
    
    @property
    def description(self) -> str:
        return (
            "Search through historical conversation memories using keywords or regex patterns. "
            "Returns relevant excerpts from past conversations. "
            "Keywords use exact matching. For flexible searches (plurals, variants, etc.), use regex_patterns. "
            "Use this when you need to recall specific past conversations or information."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of keywords for exact matching (case-insensitive). Use for simple, literal searches."
                },
                "regex_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: Regex patterns for flexible matching. Use for variants, alternatives, or complex patterns (e.g., '(volleyball|basketball)', 'Python [23]\\..+', '(ticket|price).*\\$\\d+'). Patterns are validated for safety."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50
                },
            }
        }
    
    async def execute(self, keywords: List[str] | None = None, 
                     max_results: int = 10, 
                     regex_patterns: List[str] | None = None,
                     **kwargs: Any) -> str:
        """
        Execute memory search with given keywords or regex patterns.
        """
        if not keywords and not regex_patterns:
            return "Error: No keywords or regex patterns provided"
        
        # Get all daily memory files (YYYY-MM-DD.md)
        daily_files = self._get_daily_memory_files()
        
        if not daily_files:
            return "No historical memory files found."
        
        # Search through files
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
            search_terms = ', '.join(keywords or []) if keywords else ', '.join(regex_patterns or [])
            result_msg = f"No matches found for: {search_terms}"
            logger.info(f"Memory search result: {result_msg}")
            return result_msg
        
        # Format results
        output = f"Found {len(all_results)} relevant memories:\n\n"
        for i, result in enumerate(all_results, 1):
            output += f"{i}. [{result['file']}] {result['line']}\n"
        
        logger.info(f"Memory search result: Found {len(all_results)} matches from {len(daily_files)} files. Output:\n{output}")
        
        return output
    
    def _get_daily_memory_files(self) -> List[Path]:
        """
        Get all daily memory files sorted by date (newest first).
        """
        if not self._memory_dir.exists():
            return []
        
        pattern = re.compile(r'^\d{4}-\d{2}-\d{2}\.md$')
        files = [
            f for f in self._memory_dir.iterdir()
            if f.is_file() and pattern.match(f.name)
        ]
        
        return sorted(files, reverse=True)
    
    def _grep_file(self, file_path: Path, keywords: List[str], 
                   regex_patterns: List[str] | None = None) -> List[str]:
        """
        Search a single file for keywords or regex patterns.    
        """
        patterns = []
        
        # Process keywords - exact match (escape special chars)
        for keyword in keywords:
            pattern_str = r'\b' + re.escape(keyword) + r'\b'
            try:
                patterns.append(re.compile(pattern_str, re.IGNORECASE))
            except re.error:    
                continue
                
        if regex_patterns:
            for regex_pattern in regex_patterns:
                if self._validate_regex(regex_pattern):
                    try:
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
                                break  # Move to next line after first match
                        except Exception:
                            continue
        except Exception:
            pass
        
        return results
    
    def _validate_regex(self, pattern: str) -> bool:
        """
        Validate regex pattern for safety and correctness.
        """
        if len(pattern) > 500:
            logger.warning(f"Regex pattern too long: {len(pattern)} chars")
            return False
        
        dangerous_patterns = [
            (r'\([^)]*\+[^)]*\)\+', 'nested quantifiers (x+)+'),
            (r'\([^)]*\*[^)]*\)\*', 'nested quantifiers (x*)*'),
            (r'\([^)]*\*[^)]*\)\+', 'nested quantifiers (x*)+'),
            (r'\([^)]*\+[^)]*\)\*', 'nested quantifiers (x+)*'),
            (r'{\d{3,}', 'very large repetitions {N,}'),
        ]
        
        for danger_pattern, danger_desc in dangerous_patterns:
            try:
                if re.search(danger_pattern, pattern):
                    logger.warning(f"Regex pattern contains dangerous construct: {danger_desc}")
                    return False
            except re.error:
                pass
        try:
            re.compile(pattern, re.IGNORECASE)
            return True
        except re.error as e:
            logger.warning(f"Invalid regex pattern: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error validating regex: {e}")
            return False
