"""Root execution ownership, independent of FIFO scheduling and projections."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import uuid4

from nanobot.bus.events import ExecutionAdmission, InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventPublisher
from nanobot.utils.cancellation import shield_and_drain


class ExecutionControl(Protocol):
    """Trusted adapters submit intents on the gateway event loop, never mutate state."""

    async def reserve_if_idle(
        self, msg: InboundMessage, session_key: str,
    ) -> ExecutionAdmission | None: ...

    async def request_stop(self, session_key: str, execution_id: str) -> bool: ...

    async def reject(self, admission: ExecutionAdmission) -> None: ...


@dataclass
class _Execution:
    admission: ExecutionAdmission
    msg: InboundMessage
    session_key: str
    origin_key: str
    stop_requested: bool = False
    admitted: bool = False
    input_ids: set[str] = field(default_factory=set)
    entered: bool = False
    started_at: float | None = None
    task: asyncio.Task[None] | None = None


class ExecutionLifecycle:
    """Own reservations and root tasks; the existing session worker owns their order."""

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self._publisher = RuntimeEventPublisher(bus)
        self._executions: dict[str, _Execution] = {}
        self._steering_owner: dict[str, _Execution] = {}

    def _create(self, msg: InboundMessage, session_key: str) -> _Execution:
        admission = ExecutionAdmission(uuid4().hex)
        record = _Execution(admission, msg, session_key, msg.session_key)
        self._executions[admission.execution_id] = record
        msg.execution_admission = admission
        return record

    async def reserve_if_idle(
        self, msg: InboundMessage, session_key: str,
    ) -> ExecutionAdmission | None:
        if any(record.origin_key == msg.session_key for record in self._executions.values()):
            return None
        record = self._create(msg, session_key)
        await self._publisher.execution_changed(msg, session_key, record.admission.execution_id, "queued")
        return record.admission

    async def admit(self, msg: InboundMessage, session_key: str) -> ExecutionAdmission | None:
        """Bind a transport reservation, or create an owner for a newly queued root."""
        created = msg.execution_admission is None
        if msg.execution_admission is not None:
            record = self._executions.get(msg.execution_admission.execution_id)
            if record is None:
                return None  # A retired reservation cannot be revived by late dispatch.
            record.msg = msg
            record.session_key = session_key
        else:
            record = self._create(msg, session_key)
        if not record.admitted:
            record.admitted = True
            self._steering_owner[session_key] = record
        if created:
            await self._publisher.execution_changed(msg, session_key, record.admission.execution_id, "queued")
        return record.admission

    def accept_steering(self, session_key: str, input_id: str | None) -> bool:
        """Assign accepted input to the FIFO's latest root, never to a dying one."""
        record = self._steering_owner.get(session_key)
        if record is None or record.stop_requested or (
            record.task is not None and record.task.cancelling() > 0
        ):
            return False
        if input_id is not None:
            record.input_ids.add(input_id)
        return True

    def input_ids(self, admission: ExecutionAdmission) -> frozenset[str]:
        return frozenset(self._executions[admission.execution_id].input_ids)

    def stop_requested(self, admission: ExecutionAdmission) -> bool:
        record = self._executions.get(admission.execution_id)
        return record is not None and record.stop_requested

    async def request_stop(self, session_key: str, execution_id: str) -> bool:
        record = self._executions.get(execution_id)
        if record is None or record.session_key != session_key:
            return False
        if not record.stop_requested:
            record.stop_requested = True
            task = record.task
            if task is not None and not task.done() and not task.cancelling():
                task.cancel()
            await self._publisher.execution_changed(record.msg, session_key, execution_id, "stopping")
        return True

    def has_started(self, admission: ExecutionAdmission) -> bool:
        return self._executions[admission.execution_id].started_at is not None

    async def running(self, admission: ExecutionAdmission) -> None:
        record = self._executions[admission.execution_id]
        if record.stop_requested:
            raise asyncio.CancelledError()
        record.started_at = time.time()
        await self._publisher.execution_changed(
            record.msg, record.session_key, admission.execution_id, "running", started_at=record.started_at,
        )

    async def retire(
        self, admission: ExecutionAdmission, phase: Literal["injected", "rejected", "exited"],
    ) -> None:
        record = self._executions.pop(admission.execution_id, None)
        if record is None:
            return
        if self._steering_owner.get(record.session_key) is record:
            self._steering_owner.pop(record.session_key)
        await self._publisher.execution_changed(
            record.msg, record.session_key, admission.execution_id, phase,
        )

    async def reject(self, admission: ExecutionAdmission) -> None:
        await self.retire(admission, "rejected")

    async def execute(
        self,
        msg: InboundMessage,
        session_key: str,
        invoke: Callable[[], Awaitable[None]],
        settle_cancelled: Callable[[bool], Awaitable[None]],
    ) -> None:
        """Await one independent root, including cleanup if it never got its first step."""
        admission = await self.admit(msg, session_key)
        if admission is None:
            return
        record = self._executions[admission.execution_id]
        cancelled = record.stop_requested

        async def run() -> None:
            record.entered = True
            await invoke()

        if not cancelled:
            record.task = asyncio.create_task(run())
        try:
            if record.task is not None:
                await asyncio.shield(record.task)
        except asyncio.CancelledError:
            cancelled = True
            task = record.task
            if task is not None and not task.done() and not task.cancelling():
                task.cancel()
            raise  # The caller distinguishes a root Stop from cancellation of itself.
        finally:
            await shield_and_drain(self._settle(record, cancelled, settle_cancelled))

    async def _settle(
        self, record: _Execution, cancelled: bool,
        settle_cancelled: Callable[[bool], Awaitable[None]],
    ) -> None:
        try:
            if record.task is not None:
                await asyncio.gather(record.task, return_exceptions=True)
            if cancelled:
                await settle_cancelled(record.entered)
        finally:
            await self.retire(record.admission, "exited")
