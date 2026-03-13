"""Registry for memory providers."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from nanobot.memory.base import BaseMemoryProvider

# Built-in provider imports (to ensure they're available)
_imported = False


def _ensure_imports():
    """Lazy import built-in providers to avoid circular imports."""
    global _imported
    if not _imported:
        # Import built-in providers to register them
        from nanobot.memory import filesystem  # noqa: F401
        _imported = True


class MemoryProviderRegistry:
    """Registry for memory provider types.
    
    This registry manages memory provider classes (not instances).
    Use create_provider() to instantiate a registered provider.
    
    Example:
        # Register a custom provider
        MemoryProviderRegistry.register("redis", RedisMemoryProvider)
        
        # Create an instance
        provider = MemoryProviderRegistry.create_provider("redis", {"host": "localhost"})
    """

    _providers: dict[str, type[BaseMemoryProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: type[BaseMemoryProvider]) -> None:
        """Register a memory provider class.
        
        Args:
            name: Unique identifier for this provider type
            provider_class: The provider class to register
            
        Raises:
            ValueError: If name is already registered with a different class
        """
        _ensure_imports()
        if name in cls._providers and cls._providers[name] is not provider_class:
            raise ValueError(f"Memory provider '{name}' is already registered")
        cls._providers[name] = provider_class

    @classmethod
    def unregister(cls, name: str) -> None:
        """Unregister a memory provider.
        
        Args:
            name: The provider name to unregister
        """
        cls._providers.pop(name, None)

    @classmethod
    def get(cls, name: str) -> type[BaseMemoryProvider] | None:
        """Get a provider class by name.
        
        Args:
            name: The provider name
            
        Returns:
            The provider class, or None if not found
        """
        _ensure_imports()
        return cls._providers.get(name)

    @classmethod
    def has(cls, name: str) -> bool:
        """Check if a provider is registered.
        
        Args:
            name: The provider name to check
            
        Returns:
            True if registered, False otherwise
        """
        _ensure_imports()
        return name in cls._providers

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names.
        
        Returns:
            List of registered provider names
        """
        _ensure_imports()
        return list(cls._providers.keys())

    @classmethod
    def create_provider(
        cls, 
        name: str, 
        config: dict[str, Any] | None = None
    ) -> BaseMemoryProvider:
        """Create a provider instance.
        
        Args:
            name: The provider name
            config: Configuration dictionary for the provider
            
        Returns:
            An instance of the provider
            
        Raises:
            ValueError: If provider is not registered
        """
        _ensure_imports()
        provider_class = cls._providers.get(name)
        if not provider_class:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"Unknown memory provider '{name}'. "
                f"Available: {available or 'none'}"
            )
        return provider_class(config)

    @classmethod
    def discover_providers(cls, package_name: str = "nanobot.memory.providers") -> list[str]:
        """Auto-discover providers in a package.
        
        Scans the package for modules containing BaseMemoryProvider subclasses
        and returns their names. Providers are registered when their modules
        are imported.
        
        Args:
            package_name: The package to scan (default: nanobot.memory.providers)
            
        Returns:
            List of discovered provider names
        """
        discovered = []
        try:
            package = importlib.import_module(package_name)
            for _, name, ispkg in pkgutil.iter_modules(
                package.__path__ if hasattr(package, "__path__") else []
            ):
                if ispkg:
                    continue
                try:
                    mod = importlib.import_module(f"{package_name}.{name}")
                    # Module should register itself on import
                    discovered.append(name)
                except Exception:
                    # Skip modules that fail to import
                    pass
        except ImportError:
            # Package doesn't exist
            pass
        return discovered


# Global factory function for convenience
def create_memory_provider(
    provider_type: str,
    config: dict[str, Any] | None = None,
    workspace: Any | None = None,
) -> BaseMemoryProvider:
    """Create a memory provider instance.
    
    This is the main factory function for creating memory providers.
    It handles special parameters like 'workspace' that are commonly needed.
    
    Args:
        provider_type: The type of provider to create (e.g., "filesystem", "redis")
        config: Provider-specific configuration
        workspace: Optional workspace path (injected into config if provided)
        
    Returns:
        Configured memory provider instance
        
    Raises:
        ValueError: If provider type is unknown
        
    Example:
        # Create filesystem provider (default)
        provider = create_memory_provider("filesystem", {"workspace": "/path"})
        
        # Create custom provider
        provider = create_memory_provider("redis", {"host": "localhost", "port": 6379})
    """
    config = config or {}
    
    # Inject workspace if provided and not already in config
    if workspace is not None and "workspace" not in config:
        config = {**config, "workspace": str(workspace)}
    
    # Special handling for filesystem provider - it needs workspace
    if provider_type == "filesystem" and "workspace" not in config:
        raise ValueError("Filesystem memory provider requires 'workspace' in config")
    
    return MemoryProviderRegistry.create_provider(provider_type, config)
