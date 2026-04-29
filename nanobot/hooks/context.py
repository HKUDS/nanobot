"""Hook context and result types for the HookCenter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

HookAction = Literal["continue", "short_circuit", "cancel"]


@dataclass
class HookContext:
    """Mutable context passed through hook handlers at a given hook point."""

    data: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


@dataclass
class HookResult:
    """Control-flow signal returned by a hook handler.

    action:
        "continue"      - proceed to the next handler (default)
        "short_circuit"  - skip remaining handlers, return current state
        "cancel"         - abort the originating operation
    """

    action: HookAction = "continue"
    reason: str | None = None
