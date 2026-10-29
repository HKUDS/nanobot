"""Typed runtime requests, ordered with message admission rather than turn execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from nanobot.utils.llm_runtime import LLMRuntime


@dataclass(frozen=True)
class SessionStopResult:
    status: Literal["stopped", "idle", "stale"]
    stopped_tasks: int
    turn_id: str | None


@dataclass(frozen=True)
class StopSession:
    session_key: str
    turn_id: str | None
    session_generation: str
    result: asyncio.Future[SessionStopResult]


@dataclass(frozen=True)
class SelectSessionModel:
    session_key: str
    preset: str
    session_generation: str
    result: asyncio.Future[LLMRuntime]


SessionControl = StopSession | SelectSessionModel
