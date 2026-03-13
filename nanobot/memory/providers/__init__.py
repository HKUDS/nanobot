"""Built-in memory providers.

This package contains example memory provider implementations.
Third-party providers can be registered via MemoryProviderRegistry.
"""

# Import providers to register them
from nanobot.memory.providers.in_memory import InMemoryProvider

__all__ = ["InMemoryProvider"]
