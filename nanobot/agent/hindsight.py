"""
Hindsight memory integration for nanobot.

Provides long-term memory through the Hindsight API:
- retain(): Store memories from conversation
- recall(): Retrieve relevant memories for context
- reflect(): Generate insights from accumulated memories

Hindsight API runs on localhost:8888 by default.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class HindsightConfig:
    """Configuration for Hindsight memory system."""
    
    enabled: bool = False
    base_url: str = "http://localhost:8888"
    timeout_seconds: int = 30
    
    # Memory settings
    auto_retain: bool = True  # Automatically retain after each turn
    auto_recall: bool = True  # Automatically recall before each turn
    recall_limit: int = 10    # Max memories to recall
    
    # Reflection settings
    reflect_interval: int = 10  # Reflect every N turns
    reflect_enabled: bool = True


@dataclass
class Memory:
    """A single memory from Hindsight."""
    
    id: str
    content: str
    timestamp: str
    relevance: float = 0.0
    metadata: dict = field(default_factory=dict)


class HindsightClient:
    """Async client for the Hindsight memory API."""
    
    def __init__(self, config: HindsightConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def health_check(self) -> bool:
        """Check if Hindsight API is available."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.config.base_url}/health") as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"Hindsight health check failed: {e}")
            return False
    
    async def retain(
        self,
        content: str,
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Store a memory in Hindsight.
        
        Args:
            content: The memory content to store
            metadata: Optional metadata (e.g., session_id, turn_number)
        
        Returns:
            Memory ID if successful, None otherwise
        """
        if not self.config.enabled:
            return None
        
        try:
            session = await self._get_session()
            payload = {
                "content": content,
                "metadata": metadata or {}
            }
            
            async with session.post(
                f"{self.config.base_url}/api/retain",
                json=payload
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    memory_id = data.get("id")
                    logger.debug(f"Retained memory: {memory_id}")
                    return memory_id
                else:
                    error = await resp.text()
                    logger.warning(f"Failed to retain memory: {error}")
                    return None
                    
        except Exception as e:
            logger.warning(f"Error retaining memory: {e}")
            return None
    
    async def recall(
        self,
        query: str,
        limit: Optional[int] = None
    ) -> list[Memory]:
        """
        Recall relevant memories from Hindsight.
        
        Args:
            query: The query to search for relevant memories
            limit: Maximum number of memories to return
        
        Returns:
            List of Memory objects ordered by relevance
        """
        if not self.config.enabled:
            return []
        
        try:
            session = await self._get_session()
            payload = {
                "query": query,
                "limit": limit or self.config.recall_limit
            }
            
            async with session.post(
                f"{self.config.base_url}/api/recall",
                json=payload
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    memories = [
                        Memory(
                            id=m.get("id", ""),
                            content=m.get("content", ""),
                            timestamp=m.get("timestamp", ""),
                            relevance=m.get("relevance", 0.0),
                            metadata=m.get("metadata", {})
                        )
                        for m in data.get("memories", [])
                    ]
                    logger.debug(f"Recalled {len(memories)} memories")
                    return memories
                else:
                    error = await resp.text()
                    logger.warning(f"Failed to recall memories: {error}")
                    return []
                    
        except Exception as e:
            logger.warning(f"Error recalling memories: {e}")
            return []
    
    async def reflect(
        self,
        context: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate insights from accumulated memories.
        
        Args:
            context: Optional context to guide reflection
        
        Returns:
            Reflection/insights string if successful, None otherwise
        """
        if not self.config.enabled:
            return None
        
        try:
            session = await self._get_session()
            payload = {}
            if context:
                payload["context"] = context
            
            async with session.post(
                f"{self.config.base_url}/api/reflect",
                json=payload
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    reflection = data.get("reflection")
                    logger.debug(f"Generated reflection: {reflection[:100]}...")
                    return reflection
                else:
                    error = await resp.text()
                    logger.warning(f"Failed to reflect: {error}")
                    return None
                    
        except Exception as e:
            logger.warning(f"Error reflecting: {e}")
            return None


class MemoryManager:
    """
    Manages memory operations for an agent session.
    
    Handles automatic retention after turns and recall before turns.
    """
    
    def __init__(
        self,
        client: HindsightClient,
        session_id: str
    ):
        self.client = client
        self.session_id = session_id
        self.turn_count = 0
        self._last_reflection: Optional[str] = None
    
    async def on_turn_start(
        self,
        user_message: str
    ) -> list[Memory]:
        """
        Called at the start of a turn. Recalls relevant memories.
        
        Args:
            user_message: The user's message for this turn
        
        Returns:
            List of relevant memories to include in context
        """
        if not self.client.config.auto_recall:
            return []
        
        return await self.client.recall(user_message)
    
    async def on_turn_end(
        self,
        user_message: str,
        assistant_response: str,
        summary: Optional[str] = None
    ):
        """
        Called at the end of a turn. Retains the interaction.
        
        Args:
            user_message: The user's message
            assistant_response: The assistant's response
            summary: Optional summary of the turn (from compaction)
        """
        self.turn_count += 1
        
        if not self.client.config.auto_retain:
            return
        
        # Retain the turn
        content = summary or f"User: {user_message}\n\nAssistant: {assistant_response}"
        await self.client.retain(
            content=content,
            metadata={
                "session_id": self.session_id,
                "turn_number": self.turn_count,
                "type": "turn"
            }
        )
        
        # Periodic reflection
        if (
            self.client.config.reflect_enabled and
            self.turn_count % self.client.config.reflect_interval == 0
        ):
            reflection = await self.client.reflect(
                context=f"Session {self.session_id}, turn {self.turn_count}"
            )
            if reflection:
                self._last_reflection = reflection
                # Store the reflection as well
                await self.client.retain(
                    content=f"Reflection: {reflection}",
                    metadata={
                        "session_id": self.session_id,
                        "turn_number": self.turn_count,
                        "type": "reflection"
                    }
                )
    
    def format_memories_for_context(
        self,
        memories: list[Memory],
        max_chars: int = 4000
    ) -> str:
        """
        Format memories for inclusion in the system prompt.
        
        Args:
            memories: List of memories to format
            max_chars: Maximum characters to include
        
        Returns:
            Formatted string for system prompt
        """
        if not memories:
            return ""
        
        lines = ["## Relevant Memories\n"]
        total_chars = len(lines[0])
        
        for memory in memories:
            # Format each memory
            line = f"- [{memory.timestamp}] {memory.content}\n"
            
            # Check if adding this would exceed limit
            if total_chars + len(line) > max_chars:
                lines.append("- ... (more memories available)\n")
                break
            
            lines.append(line)
            total_chars += len(line)
        
        return "".join(lines)
    
    @property
    def last_reflection(self) -> Optional[str]:
        """Get the most recent reflection."""
        return self._last_reflection


def create_memory_manager(
    config: HindsightConfig,
    session_id: str
) -> MemoryManager:
    """
    Create a memory manager for a session.
    
    Args:
        config: Hindsight configuration
        session_id: The session ID to associate memories with
    
    Returns:
        Configured MemoryManager instance
    """
    client = HindsightClient(config)
    return MemoryManager(client, session_id)


# Convenience function for quick recall
async def quick_recall(
    query: str,
    base_url: str = "http://localhost:8888",
    limit: int = 5
) -> list[Memory]:
    """
    Quick one-off memory recall without full setup.
    
    Args:
        query: The query to search for
        base_url: Hindsight API URL
        limit: Maximum memories to return
    
    Returns:
        List of relevant memories
    """
    config = HindsightConfig(enabled=True, base_url=base_url)
    client = HindsightClient(config)
    
    try:
        return await client.recall(query, limit)
    finally:
        await client.close()
