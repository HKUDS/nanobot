"""
Hindsight memory store - compatibility wrapper for agent loop integration.

This module provides the HindsightMemoryStore class expected by the agent loop,
wrapping the lower-level HindsightClient.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from .hindsight import HindsightClient, HindsightConfig, Memory

logger = logging.getLogger(__name__)


class HindsightMemoryStore:
    """
    Memory store that integrates with Hindsight API.
    
    Used by the agent loop for:
    - Recalling relevant memories before processing
    - Storing important interactions
    """
    
    def __init__(
        self,
        workspace: Path,
        base_url: str = "http://localhost:8888",
        bank_id: Optional[str] = None,
        auto_store: bool = True,
        recall_limit: int = 10,
    ):
        """
        Initialize the memory store.
        
        Args:
            workspace: Workspace path (used for bank_id if not specified)
            base_url: Hindsight API URL
            bank_id: Memory bank identifier (defaults to workspace name)
            auto_store: Automatically store messages
            recall_limit: Default number of memories to recall
        """
        self.workspace = workspace
        self.bank_id = bank_id or workspace.name
        self.auto_store = auto_store
        self.recall_limit = recall_limit
        
        # Initialize client
        config = HindsightConfig(
            enabled=True,
            base_url=base_url,
            recall_limit=recall_limit,
        )
        self.client = HindsightClient(config)
        
        # Track pending store tasks
        self._pending_tasks: list[asyncio.Task] = []
    
    async def recall_for_context(
        self,
        query: str,
        limit: Optional[int] = None
    ) -> str:
        """
        Recall relevant memories formatted for system prompt injection.
        
        Args:
            query: The query to search for (usually user's message)
            limit: Max memories to return
        
        Returns:
            Formatted string for system prompt, or empty string if none
        """
        try:
            memories = await self.client.recall(
                query=query,
                limit=limit or self.recall_limit
            )
            
            if not memories:
                return ""
            
            # Format for context
            lines = ["## Recalled Memories\n"]
            for mem in memories:
                # Truncate long memories
                content = mem.content
                if len(content) > 500:
                    content = content[:497] + "..."
                lines.append(f"- {content}\n")
            
            return "".join(lines)
            
        except Exception as e:
            logger.debug(f"Memory recall failed: {e}")
            return ""
    
    async def process_message(self, message: dict[str, Any]) -> None:
        """
        Process a message for potential storage.
        
        Args:
            message: Message dict with 'role' and 'content'
        """
        if not self.auto_store:
            return
        
        role = message.get("role", "")
        content = message.get("content", "")
        
        if not content or not isinstance(content, str):
            return
        
        # Only store substantial messages
        if len(content) < 50:
            return
        
        # Don't store tool calls/results (too noisy)
        if role == "tool" or message.get("tool_calls"):
            return
        
        try:
            await self.client.retain(
                content=f"[{role}] {content}",
                metadata={
                    "bank_id": self.bank_id,
                    "role": role,
                }
            )
        except Exception as e:
            logger.debug(f"Failed to store memory: {e}")
    
    async def store(
        self,
        content: str,
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Explicitly store a memory.
        
        Args:
            content: Memory content
            metadata: Optional metadata
        
        Returns:
            Memory ID if successful
        """
        meta = metadata or {}
        meta["bank_id"] = self.bank_id
        
        return await self.client.retain(content, meta)
    
    async def recall(
        self,
        query: str,
        limit: Optional[int] = None
    ) -> list[Memory]:
        """
        Recall memories matching a query.
        
        Args:
            query: Search query
            limit: Max results
        
        Returns:
            List of Memory objects
        """
        return await self.client.recall(query, limit)
    
    async def reflect(self, context: Optional[str] = None) -> Optional[str]:
        """
        Generate insights from memories.
        
        Args:
            context: Optional context to guide reflection
        
        Returns:
            Reflection text
        """
        return await self.client.reflect(context)
    
    async def close(self):
        """Clean up resources."""
        # Wait for pending tasks
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        
        await self.client.close()
