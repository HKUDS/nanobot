"""Session kinds declare their public identity and history access."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

SESSION_TYPE_KEY = "session_type"
PARENT_SESSION_KEY = "parent_session_key"


@dataclass(frozen=True, slots=True)
class SessionType:
    name: str
    needs_handle: bool
    public_history: bool


CONVERSATION = SessionType("conversation", needs_handle=True, public_history=True)


class SessionTypes:
    """Consume declarations from session owners without importing those owners."""

    def __init__(self) -> None:
        self._types: dict[str, SessionType] = {CONVERSATION.name: CONVERSATION}

    def register(self, session_type: SessionType) -> None:
        previous = self._types.get(session_type.name)
        if previous is not None and previous != session_type:
            raise ValueError(f"session type already registered: {session_type.name}")
        self._types[session_type.name] = session_type

    def resolve(self, metadata: Mapping[str, object]) -> SessionType | None:
        # Legacy sessions are ordinary conversations. Explicit unknown kinds
        # remain private until their owner registers the access contract.
        name = metadata.get(SESSION_TYPE_KEY, CONVERSATION.name)
        return self._types.get(name) if isinstance(name, str) else None

    def needs_handle(self, metadata: Mapping[str, object]) -> bool:
        kind = self.resolve(metadata)
        return kind is not None and kind.needs_handle

    def public_history(self, metadata: Mapping[str, object]) -> bool:
        kind = self.resolve(metadata)
        return kind is not None and kind.public_history
