"""mem0 memory integration for nanobot.

Provides semantic memory storage and retrieval using mem0.
No Docker required - runs embedded.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from loguru import logger

# Patterns that indicate user wants to store a memory
MEMORY_INTENT_PATTERNS = [
    r"\blembr[ae]\b",  # lembra, lembre
    r"\banot[ae]\b",   # anota, anote
    r"\bremember\b",
    r"\bguard[ae]\b",  # guarda, guarde
    r"\bnão esquec[ea]\b",
    r"\bdon'?t forget\b",
    r"\bsalv[ae]\b",   # salva, salve
    r"\bmemorize\b",
    r"\bmark down\b",
    r"\bnote that\b",
]

def has_memory_intent(message: str) -> bool:
    """Check if message indicates user wants to store a memory.

    Args:
        message: User message text

    Returns:
        True if memory intent detected
    """
    text = message.lower()
    for pattern in MEMORY_INTENT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

try:
    from mem0 import Memory
    MEM0_AVAILABLE = True
except ImportError:
    MEM0_AVAILABLE = False
    Memory = None


class Mem0Config:
    """Configuration for mem0 memory."""

    def __init__(
        self,
        enabled: bool = False,
        storage_path: str | None = None,
        llm_provider: str = "openai",
        llm_model: str = "gpt-4o-mini",
        embedder_provider: str = "openai",
        embedder_model: str = "text-embedding-3-small",
        auto_add: bool = False,  # Only add on explicit commands
        auto_recall: bool = True,
        recall_limit: int = 5,
        openai_api_key: str | None = None,  # Optional: override env var
    ):
        self.enabled = enabled
        self.storage_path = storage_path
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.embedder_provider = embedder_provider
        self.embedder_model = embedder_model
        self.auto_add = auto_add  # Auto-add memories after each turn
        self.auto_recall = auto_recall  # Auto-recall before each turn
        self.recall_limit = recall_limit
        self.openai_api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")


class Mem0MemoryStore:
    """Memory store using mem0 for semantic memory."""
    
    def __init__(
        self,
        config: Mem0Config,
        workspace: Path,
        user_id: str = "default",
    ):
        """Initialize mem0 memory store.
        
        Args:
            config: mem0 configuration
            workspace: Workspace path for storage
            user_id: Default user ID for memories
        """
        self.config = config
        self.workspace = workspace
        self.user_id = user_id
        self._memory: Memory | None = None
        
        if not MEM0_AVAILABLE:
            logger.warning("mem0 not available - install with: pip install mem0ai")
            return
            
        if not config.enabled:
            logger.debug("mem0 memory disabled")
            return
        
        self._init_memory()
    
    def _init_memory(self) -> None:
        """Initialize mem0 Memory instance."""
        try:
            # Get provider names from config (handle both Pydantic model and plain class)
            llm_provider = getattr(self.config, "llm_provider", "openai")
            llm_model = getattr(self.config, "llm_model", "gpt-4o-mini")
            embedder_provider = getattr(self.config, "embedder_provider", "openai")
            embedder_model = getattr(self.config, "embedder_model", "text-embedding-3-small")
            storage_path_str = getattr(self.config, "storage_path", None)

            # Configure LLM
            llm_config = {"model": llm_model}

            # Add API keys based on provider
            if llm_provider == "openai":
                api_key = os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    logger.warning("OPENAI_API_KEY not set for mem0 LLM")
                    return
                llm_config["api_key"] = api_key
            elif llm_provider == "groq":
                api_key = os.environ.get("GROQ_API_KEY")
                if not api_key:
                    logger.warning("GROQ_API_KEY not set for mem0 LLM")
                    return
                llm_config["api_key"] = api_key

            # Configure embedder
            embedder_config = {"model": embedder_model}

            if embedder_provider == "openai":
                api_key = os.environ.get("OPENAI_API_KEY")
                if api_key:
                    embedder_config["api_key"] = api_key
            # huggingface doesn't need API key - it runs locally

            mem0_config = {
                "llm": {
                    "provider": llm_provider,
                    "config": llm_config,
                },
                "embedder": {
                    "provider": embedder_provider,
                    "config": embedder_config,
                },
                "version": "v1.1",
            }

            # Add storage path if specified
            if storage_path_str:
                storage_path = Path(storage_path_str).expanduser()
                storage_path.mkdir(parents=True, exist_ok=True)
                mem0_config["vector_store"] = {
                    "provider": "qdrant",
                    "config": {
                        "collection_name": "nanobot_memories",
                        "path": str(storage_path / "qdrant"),
                    }
                }

            self._memory = Memory.from_config(mem0_config)
            logger.info(f"mem0 memory initialized (llm={llm_provider}, embedder={embedder_provider})")
            
        except Exception as e:
            logger.error(f"Failed to initialize mem0: {e}")
            self._memory = None
    
    @property
    def available(self) -> bool:
        """Check if memory is available."""
        return self._memory is not None
    
    def add(
        self,
        content: str | list[dict[str, Any]],
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Add content to memory.
        
        Args:
            content: Text or messages to remember
            user_id: User ID (defaults to instance user_id)
            metadata: Optional metadata
            
        Returns:
            Result from mem0 or None if failed
        """
        if not self.available:
            return None
        
        user_id = user_id or self.user_id
        
        try:
            result = self._memory.add(
                content,
                user_id=user_id,
                metadata=metadata or {},
            )
            logger.debug(f"Added to memory for user {user_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to add to memory: {e}")
            return None
    
    def search(
        self,
        query: str,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search memories.
        
        Args:
            query: Search query
            user_id: User ID (defaults to instance user_id)
            limit: Max results (defaults to config.recall_limit)
            
        Returns:
            List of relevant memories
        """
        if not self.available:
            return []
        
        user_id = user_id or self.user_id
        limit = limit or self.config.recall_limit
        
        try:
            result = self._memory.search(
                query=query,
                user_id=user_id,
                limit=limit,
            )
            memories = result.get("results", []) if isinstance(result, dict) else result
            logger.debug(f"Found {len(memories)} memories for query: {query[:50]}...")
            return memories
        except Exception as e:
            logger.error(f"Failed to search memory: {e}")
            return []
    
    def get_all(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Get all memories for a user.
        
        Args:
            user_id: User ID (defaults to instance user_id)
            
        Returns:
            List of all memories
        """
        if not self.available:
            return []
        
        user_id = user_id or self.user_id
        
        try:
            result = self._memory.get_all(user_id=user_id)
            memories = result.get("results", []) if isinstance(result, dict) else result
            return memories
        except Exception as e:
            logger.error(f"Failed to get all memories: {e}")
            return []
    
    def delete(self, memory_id: str) -> bool:
        """Delete a specific memory.
        
        Args:
            memory_id: ID of memory to delete
            
        Returns:
            True if successful
        """
        if not self.available:
            return False
        
        try:
            self._memory.delete(memory_id=memory_id)
            logger.debug(f"Deleted memory: {memory_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False
    
    def format_for_context(self, memories: list[dict[str, Any]]) -> str:
        """Format memories for inclusion in LLM context.
        
        Args:
            memories: List of memory objects
            
        Returns:
            Formatted string for context
        """
        if not memories:
            return ""
        
        lines = ["## Relevant Memories", ""]
        for mem in memories:
            memory_text = mem.get("memory", mem.get("content", str(mem)))
            lines.append(f"- {memory_text}")
        
        return "\n".join(lines)
    
    async def recall_for_context(self, query: str, user_id: str | None = None) -> str:
        """Search and format memories for context injection.
        
        Args:
            query: The user's message/query
            user_id: User ID
            
        Returns:
            Formatted memory context string
        """
        if not self.config.auto_recall:
            return ""
        
        memories = self.search(query, user_id=user_id)
        return self.format_for_context(memories)
    
    async def add_from_conversation(
        self,
        messages: list[dict[str, Any]],
        user_id: str | None = None,
    ) -> None:
        """Add memories from a conversation.
        
        Args:
            messages: Conversation messages
            user_id: User ID
        """
        if not self.config.auto_add or not self.available:
            return
        
        # Only add the last exchange (user + assistant)
        recent = messages[-2:] if len(messages) >= 2 else messages
        if recent:
            self.add(recent, user_id=user_id)


def create_mem0_store(
    config: Mem0Config,
    workspace: Path,
    user_id: str = "default",
) -> Mem0MemoryStore:
    """Create a mem0 memory store.
    
    Args:
        config: mem0 configuration
        workspace: Workspace path
        user_id: Default user ID
        
    Returns:
        Configured Mem0MemoryStore instance
    """
    return Mem0MemoryStore(config, workspace, user_id)
