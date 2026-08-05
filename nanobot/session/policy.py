"""Runtime-only policy for a conversation session."""

from dataclasses import dataclass
from enum import Enum


class SessionPersistence(str, Enum):
    """Where session state may be retained."""

    DURABLE = "durable"
    MEMORY_ONLY = "memory_only"


@dataclass(frozen=True, slots=True)
class SessionRuntimePolicy:
    """Non-serialized behavior fixed for the lifetime of a session."""

    persistence: SessionPersistence = SessionPersistence.DURABLE
    include_automatic_memory_context: bool = True
    allow_durable_session_work: bool = True
    log_content: bool = True


DEFAULT_SESSION_RUNTIME_POLICY = SessionRuntimePolicy()
MEMORY_ONLY_SESSION_RUNTIME_POLICY = SessionRuntimePolicy(
    persistence=SessionPersistence.MEMORY_ONLY,
    include_automatic_memory_context=False,
    allow_durable_session_work=False,
    log_content=False,
)
