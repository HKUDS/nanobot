"""Runtime-only persistence mode for a conversation session."""

from enum import Enum


class SessionPersistence(str, Enum):
    """Where session state may be retained."""

    DURABLE = "durable"
    MEMORY_ONLY = "memory_only"
