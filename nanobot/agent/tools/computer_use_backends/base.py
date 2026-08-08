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

import asyncio
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from nanobot.agent.tools.context import current_request_session_key


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


class SessionBackendPool:
    """Keep stateful backends isolated by nanobot session."""

    def __init__(
        self,
        factory: Callable[[], Any],
        injected: Any = None,
        *,
        max_backends: int = 8,
        finalizer: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if max_backends < 1:
            raise ValueError("max_backends must be at least 1")
        self._factory = factory
        self._injected = injected
        self._max_backends = max_backends
        self._finalizer = finalizer
        self._backends: OrderedDict[str, Any] = OrderedDict()
        self._lock = asyncio.Lock()
        self._closed = False

    async def get(self) -> Any:
        async with self._lock:
            if self._closed:
                raise RuntimeError("computer-use backend pool is closed")
            if self._injected is not None:
                return self._injected
            key = current_request_session_key() or "default"
            backend = self._backends.get(key)
            if backend is not None:
                self._backends.move_to_end(key)
                return backend
            if len(self._backends) >= self._max_backends:
                _, stale = self._backends.popitem(last=False)
                await stale.close()
            backend = self._factory()
            self._backends[key] = backend
            return backend

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            backends = (
                [self._injected]
                if self._injected is not None
                else list(self._backends.values())
            )
            self._injected = None
            self._backends.clear()
            finalizer, self._finalizer = self._finalizer, None
        results = await asyncio.gather(
            *(backend.close() for backend in backends if backend is not None),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if finalizer is not None:
            try:
                await finalizer()
            except BaseException as exc:
                errors.append(exc)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("failed to close computer-use backends", errors)
