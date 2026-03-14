"""Soul & Memory system for nanobot agents.

Provides agent personality (Soul) and persistent memory with hybrid search.

Modules:
  workspace: Agent workspace management (SOUL.md, MEMORY.md, memory/)
  search:    TF-IDF + BM25 hybrid memory search
  tools:     Memory tools (memory_search, memory_get, memory_write)
  prompt:    System prompt builder with soul/memory injection
  gateway:   WebSocket gateway server with soul/memory support
  repl:      Interactive REPL for testing
"""

from nanobot.soul.workspace import AgentWorkspace, load_bootstrap_files
from nanobot.soul.search import MemorySearchIndex
from nanobot.soul.tools import (
    MemoryManager,
    MemorySearchTool,
    MemoryGetTool,
    MemoryWriteTool,
    register_memory_tools,
    get_memory_manager,
)
from nanobot.soul.prompt import SoulPromptBuilder, build_soul_system_prompt

__all__ = [
    "AgentWorkspace",
    "load_bootstrap_files",
    "MemorySearchIndex",
    "MemoryManager",
    "MemorySearchTool",
    "MemoryGetTool",
    "MemoryWriteTool",
    "register_memory_tools",
    "get_memory_manager",
    "SoulPromptBuilder",
    "build_soul_system_prompt",
]
