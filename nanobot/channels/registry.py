"""Registry primitives for built-in channel metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelSpec:
    """Metadata describing a built-in channel."""

    name: str
    module: str
    display_name: str = ""

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()


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
