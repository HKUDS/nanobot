"""Backend interface for the ``computer_use`` tool.

A backend is the *actuator* + *screenshot source* for one execution environment
(the local desktop, a headless browser, a VM, ...). The tool layer owns the
agent loop, coordinate scaling, screenshot downscaling and safety gating; a
backend only has to perform primitive actions and grab a screenshot.

Coordinate contract: every ``x``/``y`` passed to a backend is already in **real
device pixels** (the same pixel space as :meth:`screenshot`). The tool scales the
model's target-space coordinates to real pixels before calling the backend, so
backends never deal with the downscaled space.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ComputerBackend(ABC):
    """Primitive GUI actions + screenshot for one execution environment."""

    #: "desktop" or "browser" — surfaced to the model so it knows the context.
    environment: str = "desktop"

    @abstractmethod
    async def dimensions(self) -> tuple[int, int]:
        """Return the real screenshot pixel size as ``(width, height)``."""

    @abstractmethod
    async def screenshot(self) -> bytes:
        """Return a PNG screenshot of the current screen at real pixel size."""

    @abstractmethod
    async def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        """Click at ``(x, y)``. ``button`` in {left,right,middle}; ``count`` for double/triple."""

    @abstractmethod
    async def move(self, x: int, y: int) -> None:
        """Move the cursor to ``(x, y)`` without clicking."""

    @abstractmethod
    async def drag(self, x: int, y: int) -> None:
        """Press at the current cursor position and drag to ``(x, y)``, then release."""

    @abstractmethod
    async def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        """Scroll at ``(x, y)``. ``direction`` in {up,down,left,right}; ``amount`` in clicks."""

    @abstractmethod
    async def type_text(self, text: str) -> None:
        """Type ``text`` at the current focus."""

    @abstractmethod
    async def key(self, combo: str) -> None:
        """Press a key or combo, e.g. ``"ctrl+s"`` / ``"Enter"`` (backend-specific syntax)."""

    async def navigate(self, url: str) -> None:
        """Navigate to ``url`` (browser backends only)."""
        raise NotImplementedError(
            f"'navigate' is not supported by the {self.environment} backend"
        )

    async def close(self) -> None:
        """Release any resources (browser process, etc.). Safe to call repeatedly."""
        return None
