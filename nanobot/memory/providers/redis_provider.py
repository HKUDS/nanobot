"""Redis-based memory provider.

This provider stores memory in Redis, enabling:
- Distributed deployments with shared memory
- Persistence across process restarts
- High-performance memory operations
- Memory sharing across multiple nanobot instances

Requirements:
    pip install redis

Configuration:
    host: Redis host (default: "localhost")
    port: Redis port (default: 6379)
    db: Redis database number (default: 0)
    password: Redis password (optional)
    key_prefix: Key prefix for all keys (default: "nanobot:memory")
    
Example:
    provider = RedisMemoryProvider({
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "key_prefix": "nanobot:memory:mybot"
    })
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

from nanobot.memory.base import BaseMemoryProvider, MemoryEntry
from nanobot.memory.registry import MemoryProviderRegistry


class RedisMemoryProvider(BaseMemoryProvider):
    """Redis-based memory provider.
    
    Stores memory in Redis with the following key structure:
    - {prefix}:long_term - Long-term memory content (string)
    - {prefix}:history - History entries (list, LPUSH for newest first)
    
    Example:
        provider = RedisMemoryProvider({
            "host": "redis.example.com",
            "port": 6379,
            "password": "secret",
            "key_prefix": "nanobot:memory"
        })
        
        provider.write_long_term("# User Info\n\nName: Alice")
        provider.append_history("[2024-01-15 10:30] Started new project")
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize Redis memory provider.
        
        Args:
            config: Redis configuration with keys:
                - host: Redis host (default: "localhost")
                - port: Redis port (default: 6379)
                - db: Database number (default: 0)
                - password: Password (optional)
                - socket_timeout: Connection timeout (default: 5)
                - key_prefix: Key prefix (default: "nanobot:memory")
        """
        super().__init__(config)
        
        if not HAS_REDIS:
            raise ImportError(
                "Redis support requires 'redis' package. "
                "Install with: pip install redis"
            )
        
        self._key_prefix = self.config.get("key_prefix", "nanobot:memory")
        self._long_term_key = f"{self._key_prefix}:long_term"
        self._history_key = f"{self._key_prefix}:history"
        
        # Build Redis connection kwargs
        redis_kwargs = {
            "host": self.config.get("host", "localhost"),
            "port": self.config.get("port", 6379),
            "db": self.config.get("db", 0),
            "socket_timeout": self.config.get("socket_timeout", 5),
            "decode_responses": True,
        }
        if self.config.get("password"):
            redis_kwargs["password"] = self.config["password"]
        
        self._client = redis.Redis(**redis_kwargs)

    @property
    def name(self) -> str:
        """Return provider name."""
        return "redis"

    def read_long_term(self) -> str:
        """Read long-term memory from Redis.
        
        Returns:
            Long-term memory content or empty string.
        """
        content = self._client.get(self._long_term_key)
        return content or ""

    def write_long_term(self, content: str) -> None:
        """Write long-term memory to Redis.
        
        Args:
            content: Complete long-term memory content.
        """
        self._client.set(self._long_term_key, content)

    def append_history(self, entry: str) -> None:
        """Append entry to history in Redis.
        
        Args:
            entry: History entry text.
        """
        # Use LPUSH to add newest entries at the beginning
        self._client.lpush(self._history_key, entry)

    def search_history(
        self,
        query: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[MemoryEntry]:
        """Search history entries.
        
        Note: This performs client-side filtering. For large histories,
        consider using Redis Search (RediSearch) module.
        
        Args:
            query: Optional text to search for
            start_time: Optional start time filter
            end_time: Optional end time filter
            limit: Maximum entries to return
            
        Returns:
            List of matching entries, newest first.
        """
        # Get all history entries (may need pagination for very large histories)
        raw_entries = self._client.lrange(self._history_key, 0, -1)
        
        results = []
        for raw_entry in raw_entries:
            # Try to parse timestamp
            timestamp = datetime.now()
            if raw_entry.startswith("[") and "]" in raw_entry:
                time_str = raw_entry[1:raw_entry.find("]")]
                try:
                    timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                except ValueError:
                    pass

            # Apply filters
            if start_time and timestamp < start_time:
                continue
            if end_time and timestamp > end_time:
                continue
            if query and query.lower() not in raw_entry.lower():
                continue

            results.append(MemoryEntry(
                content=raw_entry,
                timestamp=timestamp,
                entry_type="history",
            ))

        return results[:limit]

    def get_memory_context(self) -> str:
        """Get formatted memory context.
        
        Returns:
            Long-term memory with header, or empty string.
        """
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    def close(self) -> None:
        """Close Redis connection."""
        self._client.close()

    @property
    def is_available(self) -> bool:
        """Check if Redis is accessible.
        
        Returns:
            True if Redis connection works.
        """
        try:
            return self._client.ping()
        except Exception:
            return False

    def clear(self) -> None:
        """Clear all memory from Redis."""
        self._client.delete(self._long_term_key, self._history_key)

    def get_history_count(self) -> int:
        """Get number of history entries.
        
        Returns:
            Count of history entries in Redis.
        """
        return self._client.llen(self._history_key)


# Register the provider (only if redis is available)
if HAS_REDIS:
    MemoryProviderRegistry.register("redis", RedisMemoryProvider)
