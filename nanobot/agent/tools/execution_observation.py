"""Execution-owner facts attached to a tool result, not model-facing text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExecutionFinishReason = Literal[
    "exit", "max_runtime", "idle_timeout", "cancelled", "owner_closed", "shutdown", "execution_error",
]


@dataclass(frozen=True, slots=True)
class ExecutionObservation:
    """A bounded snapshot at observation time; the ID cannot control the process."""

    activity_id: str
    command: str
    observed_at: float
    sequence: int
    done: bool
    stopping: bool
    exit_code: int | None
    finish_reason: ExecutionFinishReason | None
    output: str
    truncated_chars: int
    output_incomplete: bool
    execution_error: str | None
    started: bool = False
