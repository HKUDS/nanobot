"""Memory plugin system for nanobot.

This module provides a pluggable memory system that allows third-party
providers to implement custom memory storage backends.

Usage:
    # Using built-in filesystem provider (default)
    from nanobot.memory import create_memory_provider
    provider = create_memory_provider("filesystem", {"workspace": "/path"})
    
    # Using in-memory provider (for testing)
    provider = create_memory_provider("in_memory")
    
    # Using Redis provider (requires redis package)
    provider = create_memory_provider("redis", {
        "host": "localhost",
        "port": 6379
    })
    
    # Creating a custom provider
    from nanobot.memory import BaseMemoryProvider, MemoryProviderRegistry
    
    class MyProvider(BaseMemoryProvider):
        def read_long_term(self) -> str:
            # Implementation...
            pass
        # ... implement other methods
    
    MemoryProviderRegistry.register("my_provider", MyProvider)
"""

from nanobot.memory.base import BaseMemoryProvider, MemoryEntry
from nanobot.memory.registry import MemoryProviderRegistry, create_memory_provider
from nanobot.memory.filesystem import FilesystemMemoryProvider

# Import providers to register them
from nanobot.memory import providers

__all__ = [
    "BaseMemoryProvider",
    "MemoryEntry",
    "MemoryProviderRegistry",
    "create_memory_provider",
    "FilesystemMemoryProvider",
]
