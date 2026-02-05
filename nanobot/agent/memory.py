"""Memory system for persistent agent memory."""

from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional

from nanobot.utils.helpers import ensure_dir, today_date
from nanobot.agent.retrieval import MemoryRetriever, split_markdown_into_chunks


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
        """Get path to today's memory file."""
        return self.memory_dir / f"{today_date()}.md"
    
    def read_today(self) -> str:
        """Read today's memory notes."""
        today_file = self.get_today_file()
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""
    
    def append_today(self, content: str) -> None:
        """Append content to today's memory notes."""
        today_file = self.get_today_file()
        
        if today_file.exists():
            existing = today_file.read_text(encoding="utf-8")
            content = existing + "\n" + content
        else:
            # Add header for new day
            header = f"# {today_date()}\n\n"
            content = header + content
        
        today_file.write_text(content, encoding="utf-8")
    
    def read_long_term(self) -> str:
        """Read long-term memory (MEMORY.md)."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""
    
    def write_long_term(self, content: str) -> None:
        """Write to long-term memory (MEMORY.md)."""
        self.memory_file.write_text(content, encoding="utf-8")
    
    def get_recent_memories(self, days: int = 7) -> str:
        """
        Get memories from the last N days.
        
        Args:
            days: Number of days to look back.
        
        Returns:
            Combined memory content.
        """
        memories = []
        today = datetime.now().date()
        
        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            file_path = self.memory_dir / f"{date_str}.md"
            
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                memories.append(content)
        
        return "\n\n---\n\n".join(memories)
    
    def list_memory_files(self) -> List[Path]:
        """List all memory files sorted by date (newest first)."""
        if not self.memory_dir.exists():
            return []
        
        files = list(self.memory_dir.glob("????-??-??.md"))
        return sorted(files, reverse=True)
    
    def get_memory_context(self, query: Optional[str] = None, top_k: int = 5) -> str:
        """
        Get memory context for the agent.
        
        If a query is provided, it uses BM25 retrieval to find relevant chunks.
        Otherwise, it returns the standard context (long-term + today).
        
        Args:
            query: Optional query string for retrieval.
            top_k: Number of relevant chunks to retrieve.
            
        Returns:
            Formatted memory context.
        """
        if not query:
            parts = []
            long_term = self.read_long_term()
            if long_term:
                parts.append("## Long-term Memory\n" + long_term)
            today = self.read_today()
            if today:
                parts.append("## Today's Notes\n" + today)
            return "\n\n".join(parts) if parts else ""

        # Retrieval mode
        all_content = []
        
        # Add long-term memory
        long_term = self.read_long_term()
        if long_term:
            all_content.append(long_term)
            
        # Add recent memories (last 30 days for retrieval)
        recent = self.get_recent_memories(days=30)
        if recent:
            all_content.append(recent)
            
        if not all_content:
            return ""
            
        full_text = "\n\n".join(all_content)
        chunks = split_markdown_into_chunks(full_text)
        
        if not chunks:
            return ""
            
        retriever = MemoryRetriever(chunks)
        results = retriever.retrieve(query, top_k=top_k)
        
        if not results:
            # Fallback to standard context if no matches
            return self.get_memory_context(query=None)
            
        relevant_chunks = [chunk for chunk, score in results]
        return "## Relevant Memories\n\n" + "\n\n---\n\n".join(relevant_chunks)
