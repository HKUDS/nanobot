"""Shared contracts for chat channels."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel


def __getattr__(name: str) -> type[BaseChannel]:
    if name != "BaseChannel":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from nanobot.channels.base import BaseChannel

    globals()[name] = BaseChannel
    return BaseChannel


__all__ = ["BaseChannel"]
