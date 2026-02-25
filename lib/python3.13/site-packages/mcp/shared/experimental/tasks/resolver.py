"""
Resolver - An anyio-compatible future-like object for async result passing.

This provides a simple way to pass a result (or exception) from one coroutine
to another without depending on asyncio.Future.
"""

from typing import Generic, TypeVar, cast

import anyio

T = TypeVar("T")


class Resolver(Generic[T]):
    """
    A simple resolver for passing results between coroutines.

    Unlike asyncio.Future, this works with any anyio-compatible async backend.

    Usage:
        resolver: Resolver[str] = Resolver()

        # In one coroutine:
        resolver.set_result("hello")

        # In another coroutine:
        result = await resolver.wait()  # returns "hello"
    """

    def __init__(self) -> None:
        self._event = anyio.Event()
        self._value: T | None = None
        self._exception: BaseException | None = None

    def set_result(self, value: T) -> None:
        """Set the result value and wake up waiters."""
        if self._event.is_set():
            raise RuntimeError("Resolver already completed")
        self._value = value
        self._event.set()

    def set_exception(self, exc: BaseException) -> None:
        """Set an exception and wake up waiters."""
        if self._event.is_set():
            raise RuntimeError("Resolver already completed")
        self._exception = exc
        self._event.set()

    async def wait(self) -> T:
        """Wait for the result and return it, or raise the exception."""
        await self._event.wait()
        if self._exception is not None:
            raise self._exception
        # If we reach here, set_result() was called, so _value is set
        return cast(T, self._value)

    def done(self) -> bool:
        """Return True if the resolver has been completed."""
        return self._event.is_set()
