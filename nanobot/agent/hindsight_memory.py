"""Hindsight memory integration - self-learning agent memory."""

import asyncio
import httpx
from typing import Any
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


DEFAULT_HINDSIGHT_URL = "http://localhost:8888"
DEFAULT_BANK_ID = "nanobot"


@dataclass
class MemoryResult:
    """Result from a memory recall operation."""
    content: str
    score: float
    metadata: dict[str, Any]


@dataclass
class ReflectResult:
    """Result from a reflect operation."""
    response: str
    memories_used: list[str]


class HindsightClient:
    """
    Client for Hindsight memory system.
    
    Hindsight provides self-learning memory for AI agents.
    See: https://github.com/vectorize-io/hindsight
    """
    
    def __init__(
        self,
        base_url: str = DEFAULT_HINDSIGHT_URL,
        bank_id: str = DEFAULT_BANK_ID,
        timeout: float = 30.0,
    ):
        """
        Initialize Hindsight client.
        
        Args:
            base_url: URL of Hindsight server.
            bank_id: Memory bank ID (namespace for memories).
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.bank_id = bank_id
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def is_available(self) -> bool:
        """Check if Hindsight server is available."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False
    
    async def retain(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Store a memory in Hindsight.
        
        Args:
            content: Content to remember.
            metadata: Optional metadata to store with memory.
        
        Returns:
            True if successful.
        """
        try:
            client = await self._get_client()
            response = await client.post(
                "/retain",
                json={
                    "bank_id": self.bank_id,
                    "content": content,
                    "metadata": metadata or {},
                },
            )
            
            if response.status_code in (200, 201):
                logger.debug(f"Retained memory: {content[:100]}...")
                return True
            else:
                logger.warning(f"Retain failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Hindsight retain error: {e}")
            return False
    
    async def recall(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.0,
    ) -> list[MemoryResult]:
        """
        Search memories in Hindsight.
        
        Args:
            query: Search query.
            limit: Maximum number of results.
            min_score: Minimum similarity score (0-1).
        
        Returns:
            List of matching memories.
        """
        try:
            client = await self._get_client()
            response = await client.post(
                "/recall",
                json={
                    "bank_id": self.bank_id,
                    "query": query,
                    "limit": limit,
                },
            )
            
            if response.status_code != 200:
                logger.warning(f"Recall failed: {response.status_code}")
                return []
            
            data = response.json()
            results = []
            
            for item in data.get("results", []):
                score = item.get("score", 0.0)
                if score >= min_score:
                    results.append(MemoryResult(
                        content=item.get("content", ""),
                        score=score,
                        metadata=item.get("metadata", {}),
                    ))
            
            return results
            
        except Exception as e:
            logger.error(f"Hindsight recall error: {e}")
            return []
    
    async def reflect(
        self,
        query: str,
        context: str | None = None,
    ) -> ReflectResult | None:
        """
        Generate a disposition-aware response using memories.
        
        This is more advanced than recall - it synthesizes memories
        into a coherent response.
        
        Args:
            query: Question or prompt.
            context: Optional additional context.
        
        Returns:
            ReflectResult with response and memories used.
        """
        try:
            client = await self._get_client()
            payload = {
                "bank_id": self.bank_id,
                "query": query,
            }
            if context:
                payload["context"] = context
            
            response = await client.post("/reflect", json=payload)
            
            if response.status_code != 200:
                logger.warning(f"Reflect failed: {response.status_code}")
                return None
            
            data = response.json()
            return ReflectResult(
                response=data.get("response", ""),
                memories_used=data.get("memories_used", []),
            )
            
        except Exception as e:
            logger.error(f"Hindsight reflect error: {e}")
            return None
    
    async def forget(
        self,
        content: str | None = None,
        memory_id: str | None = None,
    ) -> bool:
        """
        Remove a memory from Hindsight.
        
        Args:
            content: Content to forget (matches exact content).
            memory_id: Specific memory ID to remove.
        
        Returns:
            True if successful.
        """
        try:
            client = await self._get_client()
            payload = {"bank_id": self.bank_id}
            
            if memory_id:
                payload["memory_id"] = memory_id
            elif content:
                payload["content"] = content
            else:
                return False
            
            response = await client.post("/forget", json=payload)
            return response.status_code in (200, 204)
            
        except Exception as e:
            logger.error(f"Hindsight forget error: {e}")
            return False


class HindsightMemoryStore:
    """
    Memory store that integrates Hindsight with nanobot.
    
    Provides automatic memory retention and recall during conversations.
    """
    
    def __init__(
        self,
        workspace: Path,
        base_url: str = DEFAULT_HINDSIGHT_URL,
        bank_id: str | None = None,
        auto_retain: bool = True,
        recall_limit: int = 5,
    ):
        """
        Initialize memory store.
        
        Args:
            workspace: Workspace path (used for bank_id if not specified).
            base_url: Hindsight server URL.
            bank_id: Memory bank ID (defaults to workspace name).
            auto_retain: Automatically retain important messages.
            recall_limit: Default number of memories to recall.
        """
        self.workspace = workspace
        self.auto_retain = auto_retain
        self.recall_limit = recall_limit
        
        # Use workspace name as bank_id if not specified
        if bank_id is None:
            bank_id = workspace.name or DEFAULT_BANK_ID
        
        self.client = HindsightClient(base_url=base_url, bank_id=bank_id)
        self._available: bool | None = None
    
    async def check_available(self) -> bool:
        """Check if Hindsight is available (cached)."""
        if self._available is None:
            self._available = await self.client.is_available()
            if self._available:
                logger.info("Hindsight memory system connected")
            else:
                logger.debug("Hindsight not available, using local memory only")
        return self._available
    
    async def remember(
        self,
        content: str,
        source: str = "conversation",
        importance: str = "normal",
    ) -> bool:
        """
        Store a memory.
        
        Args:
            content: Content to remember.
            source: Source of the memory (conversation, user, system).
            importance: Importance level (low, normal, high).
        
        Returns:
            True if stored successfully.
        """
        if not await self.check_available():
            return False
        
        return await self.client.retain(
            content=content,
            metadata={
                "source": source,
                "importance": importance,
                "workspace": str(self.workspace),
            },
        )
    
    async def recall_for_context(
        self,
        query: str,
        limit: int | None = None,
    ) -> str:
        """
        Recall relevant memories and format for context injection.
        
        Args:
            query: Query to search for relevant memories.
            limit: Maximum memories to return.
        
        Returns:
            Formatted string of relevant memories.
        """
        if not await self.check_available():
            return ""
        
        results = await self.client.recall(
            query=query,
            limit=limit or self.recall_limit,
            min_score=0.3,
        )
        
        if not results:
            return ""
        
        parts = ["## Relevant Memories\n"]
        for i, mem in enumerate(results, 1):
            score_pct = int(mem.score * 100)
            parts.append(f"{i}. [{score_pct}%] {mem.content}")
        
        return "\n".join(parts)
    
    async def should_retain_message(
        self,
        message: dict[str, Any],
    ) -> bool:
        """
        Determine if a message should be retained in long-term memory.
        
        Uses heuristics to identify important information.
        
        Args:
            message: Message to evaluate.
        
        Returns:
            True if message should be retained.
        """
        if not self.auto_retain:
            return False
        
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        
        content_lower = content.lower()
        
        # Heuristics for important content
        importance_indicators = [
            # User preferences
            "i prefer", "i like", "i don't like", "i hate",
            "my favorite", "my preference",
            # Facts about user
            "my name is", "i am", "i work", "i live",
            "my email", "my phone", "my address",
            # Decisions
            "we decided", "let's go with", "the plan is",
            # Important info
            "remember that", "don't forget", "important:",
            "key point", "note:", "todo:",
            # Dates and events
            "my birthday", "appointment", "meeting",
            "deadline", "due date",
        ]
        
        for indicator in importance_indicators:
            if indicator in content_lower:
                return True
        
        # Also retain if explicitly marked
        if "[remember]" in content_lower or "[important]" in content_lower:
            return True
        
        return False
    
    async def process_message(
        self,
        message: dict[str, Any],
    ) -> None:
        """
        Process a message for potential memory retention.
        
        Args:
            message: Message to process.
        """
        if await self.should_retain_message(message):
            content = message.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            
            role = message.get("role", "unknown")
            await self.remember(
                content=content,
                source=f"conversation:{role}",
                importance="high",
            )
    
    async def close(self) -> None:
        """Close the memory store."""
        await self.client.close()


# Convenience function for quick setup
def create_memory_store(
    workspace: Path,
    hindsight_url: str | None = None,
) -> HindsightMemoryStore:
    """
    Create a memory store with default settings.
    
    Args:
        workspace: Workspace path.
        hindsight_url: Optional Hindsight server URL.
    
    Returns:
        Configured HindsightMemoryStore.
    """
    return HindsightMemoryStore(
        workspace=workspace,
        base_url=hindsight_url or DEFAULT_HINDSIGHT_URL,
    )
