"""Memory tools for searching and storing agent memory."""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class MemorySearchTool(Tool):
    """Search through memory files for relevant context."""
    
    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._memory_dir = workspace / "memory"

    @property
    def name(self) -> str:
        return "memory_search"
    
    @property
    def description(self) -> str:
        return (
            "Search through memory files (MEMORY.md and daily notes) for relevant context. "
            "Returns excerpts ranked by relevance to your query. "
            "Use this when you need to recall specific information from past conversations."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What you're looking for (keywords or phrase)"
                },
                "days": {
                    "type": "integer",
                    "description": "How many days back to search (default: 30)",
                    "minimum": 1,
                    "maximum": 365,
                    "default": 30
                },
                "max_results": {
                    "type": "integer", 
                    "description": "Maximum results to return (default: 5)",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, query: str, days: int = 30, max_results: int = 5, **kwargs: Any) -> str:
        try:
            results = self._search(query, days, max_results)
            if not results:
                return f"No memories found matching '{query}' in the last {days} days."
            
            lines = [f"Found {len(results)} relevant memories for '{query}':\n"]
            for score, source, excerpt in results:
                lines.append(f"---\n**{source}** (relevance: {score:.2f})\n{excerpt}\n")
            return "\n".join(lines)
            
        except Exception as e:
            return f"Error searching memory: {str(e)}"
    
    def _search(self, query: str, days: int, max_results: int) -> list[tuple[float, str, str]]:
        """Search memory files and return scored results."""
        query_terms = set(query.lower().split())
        results: list[tuple[float, str, str]] = []
        
        # Search long-term memory
        memory_file = self._memory_dir / "MEMORY.md"
        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            score = self._score_content(content, query_terms)
            if score > 0:
                excerpt = self._extract_excerpt(content, query_terms)
                results.append((score * 1.2, "Long-term Memory (MEMORY.md)", excerpt))  # Boost long-term
        
        # Search daily notes
        today = datetime.now().date()
        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            daily_file = self._memory_dir / f"{date_str}.md"
            
            if daily_file.exists():
                content = daily_file.read_text(encoding="utf-8")
                score = self._score_content(content, query_terms)
                # Recency boost: newer files get higher scores
                recency_boost = 1.0 + (0.1 * (days - i) / days)
                score *= recency_boost
                
                if score > 0.5:  # Threshold to avoid noise
                    excerpt = self._extract_excerpt(content, query_terms)
                    results.append((score, f"Daily Notes ({date_str})", excerpt))
        
        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:max_results]
    
    def _score_content(self, content: str, query_terms: set[str]) -> float:
        """Score content based on keyword matches."""
        content_lower = content.lower()
        words = set(re.findall(r'\b\w+\b', content_lower))
        
        matches = len(query_terms & words)
        if not matches:
            return 0.0
        
        # Simple scoring: matches / query size, normalized by content length
        coverage = matches / len(query_terms)
        density = matches / (len(words) + 1) * 100  # Boost dense matches
        return coverage * 0.6 + min(density, 1.0) * 0.4
    
    def _extract_excerpt(self, content: str, query_terms: set[str], max_chars: int = 400) -> str:
        """Extract a relevant excerpt around matching terms."""
        content_lower = content.lower()
        
        # Find first occurrence of any query term
        best_pos = -1
        for term in query_terms:
            pos = content_lower.find(term)
            if pos != -1 and (best_pos == -1 or pos < best_pos):
                best_pos = pos
        
        if best_pos == -1:
            return content[:max_chars].strip() + ("..." if len(content) > max_chars else "")
        
        # Extract context around the match
        start = max(0, best_pos - 100)
        end = min(len(content), best_pos + max_chars - 100)
        excerpt = content[start:end].strip()
        
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(content):
            excerpt = excerpt + "..."
        
        return excerpt


class MemoryRememberTool(Tool):
    """Store a structured fact in memory."""
    
    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._memory_dir = workspace / "memory"
        self._facts_file = self._memory_dir / "facts.json"

    @property
    def name(self) -> str:
        return "memory_remember"
    
    @property
    def description(self) -> str:
        return (
            "Store a fact or important information for future recall. "
            "The fact will be saved to structured storage and also appended to MEMORY.md. "
            "Use tags to categorize the fact (e.g., ['project', 'preference', 'important'])."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The fact or information to remember"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags to categorize this fact (optional)",
                    "default": []
                },
                "append_to_long_term": {
                    "type": "boolean",
                    "description": "Also append to MEMORY.md (default: true)",
                    "default": True
                }
            },
            "required": ["fact"]
        }
    
    async def execute(self, fact: str, tags: list[str] = None, append_to_long_term: bool = True, **kwargs: Any) -> str:
        try:
            tags = tags or []
            timestamp = datetime.now().isoformat()
            
            # Ensure memory directory exists
            self._memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Load existing facts
            facts = []
            if self._facts_file.exists():
                try:
                    facts = json.loads(self._facts_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    facts = []
            
            # Add new fact
            fact_entry = {
                "timestamp": timestamp,
                "tags": tags,
                "content": fact
            }
            facts.append(fact_entry)
            
            # Save facts
            self._facts_file.write_text(json.dumps(facts, indent=2), encoding="utf-8")
            
            # Also append to MEMORY.md if requested
            if append_to_long_term:
                memory_file = self._memory_dir / "MEMORY.md"
                entry_md = f"\n- **{timestamp[:10]}** ({', '.join(tags) if tags else 'general'}): {fact}\n"
                
                if memory_file.exists():
                    existing = memory_file.read_text(encoding="utf-8")
                    memory_file.write_text(existing + entry_md, encoding="utf-8")
                else:
                    memory_file.write_text(f"# Long-Term Memory\n{entry_md}", encoding="utf-8")
            
            tag_str = f" [tags: {', '.join(tags)}]" if tags else ""
            return f"✓ Remembered: {fact[:80]}{'...' if len(fact) > 80 else ''}{tag_str}"
            
        except Exception as e:
            return f"Error storing memory: {str(e)}"
