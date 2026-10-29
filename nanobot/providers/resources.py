"""Event-loop-affine ownership of cached providers and their active executions."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import TypeVar

from loguru import logger

from nanobot.providers.base import LLMProvider
from nanobot.utils.cancellation import shield_and_drain

_T = TypeVar("_T")


class ProviderLease:
    """An eagerly acquired execution reference, also transferable to queued work."""

    def __init__(self, resource: ProviderResource | None = None) -> None:
        self._resource = resource
        if resource is not None:
            resource.acquire()

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def bind(self, execution: asyncio.Future[_T]) -> None:
        """Transfer this lease to queued work, including cancellation before start."""
        if self._resource is not None:
            execution.add_done_callback(self._execution_done)

    def _execution_done(self, execution: asyncio.Future[_T]) -> None:
        self._release()

    def _release(self) -> asyncio.Task[None] | None:
        resource, self._resource = self._resource, None
        return resource.release() if resource is not None else None

    async def aclose(self) -> None:
        closing = self._release()
        if closing is not None:
            await shield_and_drain(closing)


class ProviderResource:
    """One owned provider; cache eligibility and execution references are independent."""

    def __init__(self, provider: LLMProvider, owner: ProviderResourcePool) -> None:
        self.provider = provider
        self.owner = owner
        self.retained = False
        self.users = 0
        self.closed = False
        self.idle = asyncio.Event()
        self.idle.set()
        self.close_task: asyncio.Task[None] | None = None

    def acquire(self) -> None:
        if self.closed or self.owner.closed:
            raise RuntimeError("model provider resource is closed")
        self.users += 1
        self.idle.clear()
        self.owner.collect()

    def release(self) -> asyncio.Task[None] | None:
        self.users -= 1
        if self.users == 0:
            self.idle.set()
            self.owner.collect()
            if not self.retained:
                return self.close_task
        return None


class ProviderResourcePool:
    """Own only cached, executing, or closing providers, never all resolution history."""

    def __init__(self) -> None:
        self.closed = False
        self._resources: dict[LLMProvider, ProviderResource] = {}
        self._errors: list[BaseException] = []
        self._shutdown: asyncio.Task[None] | None = None

    def get(self, provider: LLMProvider) -> ProviderResource | None:
        return self._resources.get(provider)

    def register(self, provider: LLMProvider) -> ProviderResource:
        if self.closed:
            raise RuntimeError("model runtime resolver is closed")
        resource = self._resources.get(provider)
        if resource is None:
            resource = self._resources[provider] = ProviderResource(provider, self)
        return resource

    def retain(self, resources: Iterable[ProviderResource]) -> None:
        retained = set(resources)
        for resource in self._resources.values():
            resource.retained = resource in retained
        self.collect()

    def collect(self) -> None:
        # Construction and configuration selection can also happen before an event
        # loop starts. The next execution lease or aclose drains those retirements.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for resource in self._resources.values():
            if resource.retained or resource.users or resource.close_task is not None:
                continue
            task = resource.close_task = loop.create_task(self._close_unused(resource))
            task.add_done_callback(self._observe_close)

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()  # Errors are retained for final aclose, even without a waiter.

    async def _close_unused(self, resource: ProviderResource) -> None:
        try:
            # A synchronous lookup may immediately acquire a lease before this task
            # starts. Only the actual close transition makes it unavailable.
            if resource.retained or resource.users:
                return
            resource.closed = True
            await resource.provider.aclose()
        except BaseException as exc:
            self._errors.append(exc)
            logger.error("Model provider cleanup failed ({})", type(exc).__name__)
            raise
        finally:
            resource.close_task = None
            if resource.closed:
                self._resources.pop(resource.provider, None)

    async def aclose(self) -> None:
        """Reject new leases, wait for existing executions, then close every owner."""
        if self._shutdown is None:
            self.closed = True
            self._shutdown = asyncio.create_task(self._close_all())
        await shield_and_drain(self._shutdown)

    async def _close_all(self) -> None:
        resources = tuple(self._resources.values())
        for resource in resources:
            resource.retained = False
        await asyncio.gather(*(resource.idle.wait() for resource in resources))
        self.collect()
        await asyncio.gather(*(
            resource.close_task for resource in resources if resource.close_task is not None
        ), return_exceptions=True)
        if self._errors:
            raise BaseExceptionGroup("failed to close model providers", self._errors)
