"""Structured session-summary values used while building model context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """A consolidated session checkpoint before presentation formatting."""

    text: str
    last_active: datetime

    def for_prompt(self) -> str:
        return (
            f"Previous conversation summary (last active {self.last_active.isoformat()}):\n"
            f"{self.text}"
        )

    @classmethod
    def from_metadata(
        cls,
        metadata: Mapping[str, object] | None,
        *,
        fallback_last_active: datetime,
    ) -> SessionSummary | None:
        raw: object = metadata.get("_last_summary") if metadata is not None else None
        if not isinstance(raw, Mapping):
            return None
        summary_data = cast(Mapping[str, object], raw)
        text = summary_data.get("text")
        if not isinstance(text, str) or not text:
            return None
        raw_last_active = summary_data.get("last_active")
        try:
            last_active = (
                datetime.fromisoformat(raw_last_active)
                if isinstance(raw_last_active, str)
                else fallback_last_active
            )
        except ValueError:
            last_active = fallback_last_active
        return cls(text=text, last_active=last_active)
