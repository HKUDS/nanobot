"""Registry primitives for built-in channel metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


def _default_extra_kwargs_factory() -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class ChannelSpec:
    """Metadata describing a built-in channel."""

    name: str
    module_path: str
    class_name: str
    display_name: str = ""
    extra_kwargs_factory: Callable[[], dict[str, Any]] = field(
        default=_default_extra_kwargs_factory,
    )

    def __post_init__(self) -> None:
        for field_name in ("name", "module_path", "class_name"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")


class ChannelRegistry:
    """In-memory registry for built-in channel specs."""

    def __init__(self) -> None:
        self._specs: dict[str, ChannelSpec] = {}

    def register(self, spec: ChannelSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"channel already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ChannelSpec | None:
        return self._specs.get(name)

    def all(self) -> tuple[ChannelSpec, ...]:
        return tuple(self._specs.values())
