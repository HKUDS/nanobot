"""Dict key helpers for persisted JSON that mixes camelCase and snake_case."""

from __future__ import annotations

from typing import Any


def get_camel_snake(
    data: dict[str, Any],
    camel: str,
    snake: str,
    default: Any = None,
) -> Any:
    """Prefer camelCase store keys, fall back to snake_case (asdict / hand-edits)."""
    if camel in data:
        return data[camel]
    return data.get(snake, default)
