"""Base classes for the hook system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class HookContext:
    """Context passed to every hook execution."""

    event_type: str
    session_id: Optional[str] = None
    session_key: Optional[str] = None
    sender_id: Optional[str] = None
    channel: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class Hook(ABC):
    """Abstract base for hooks."""

    name: str = ""

    @abstractmethod
    async def execute(self, context: HookContext, **kwargs: Any) -> Any:
        """Execute the hook. Return value depends on event type."""
        ...
