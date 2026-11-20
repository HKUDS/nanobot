"""Execution-local input authorization and optional sustained-run guidance."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import Protocol

from nanobot.bus.events import InboundMessage


class ExecutionControlError(RuntimeError):
    """An input control operation failed."""


class ExecutionScope(Protocol):
    def consume_inputs(self, messages: Iterable[InboundMessage]) -> None: ...

    async def continuation_prompt(self) -> str | None: ...


class ExecutionPolicy(Protocol):
    def scope(
        self, session_key: str | None, generation: str | None, *, persistent: bool,
    ) -> AbstractContextManager[ExecutionScope]: ...
