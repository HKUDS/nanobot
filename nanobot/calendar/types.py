"""Calendar data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CalendarEvent:
    """Unified internal event model used across all providers."""

    id: str
    provider: str
    calendar_id: str
    title: str
    start_at: str  # ISO 8601 datetime string with timezone
    end_at: str  # ISO 8601 datetime string with timezone
    timezone: str
    description: str = ""
    location: str = ""
    attendees: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = 0
    updated_at_ms: int = 0


@dataclass
class FreeSlot:
    """Suggested free time slot."""

    start_at: str
    end_at: str
    duration_minutes: int

