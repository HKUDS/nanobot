"""HookCenter handler protocol and return types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class Modified:
    """Returned by transform-mode handlers to indicate data was modified.

    The ``data`` field carries the transformed value that replaces the
    original event data in the pipeline.
    """

    data: Any


@dataclass(slots=True)
class Deny:
    """Returned by guard-mode handlers to block an operation.

    ``reason`` is a human-readable string explaining the denial.
    The caller (emit site) decides how to act on it — soft-deny
    (inject reason into the conversation) or hard-deny (abort the
    agent loop entirely).

    When ``abort`` is ``False`` (default), the operation is denied
    but the agent loop continues — the reason is injected as a tool
    result so the LLM can adapt.  When ``abort`` is ``True``, the
    agent loop terminates immediately and ``reason`` becomes the
    final content returned to the caller.
    """

    reason: str
    abort: bool = False


HookResult = Modified | Deny | None


class HookHandler(Protocol):
    """Protocol for hook handlers.

    Handlers accept an event dataclass and may return:
    - ``None``: observe only, no action needed
    - ``Modified(data)``: the event data was transformed
    - ``Deny(reason)``: the operation is denied
    """

    async def __call__(self, event: Any) -> HookResult: ...
