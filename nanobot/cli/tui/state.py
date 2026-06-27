"""State objects for the lightweight CLI TUI surface."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CliTuiState:
    model: str
    preset: str
    workspace: Path
    access_mode: str
    session_id: str
    active_chat_id: str = ""  # mutable publish target; /resume and /fork switch it
    status: str = "idle"
    show_logs: bool = False
    show_reasoning: bool = True
    turn_active: bool = False
    turn_started_at: float | None = None
    current_tool: str = ""

    def begin_turn(self) -> None:
        self.turn_active = True
        self.status = "thinking"
        self.turn_started_at = time.monotonic()
        self.current_tool = ""

    def note_responding(self) -> None:
        if self.turn_active:
            self.status = "responding"
            self.current_tool = ""

    def note_thinking(self) -> None:
        if self.turn_active:
            self.status = "thinking"
            self.current_tool = ""

    def note_tool(self, name: str) -> None:
        if self.turn_active:
            self.status = "tool"
            self.current_tool = name

    def end_turn(self) -> None:
        self.turn_active = False
        self.status = "idle"
        self.turn_started_at = None
        self.current_tool = ""

    @property
    def elapsed_seconds(self) -> int:
        if self.turn_started_at is None:
            return 0
        return max(0, int(time.monotonic() - self.turn_started_at))

    @property
    def status_label(self) -> str:
        if not self.turn_active:
            return "Ready"
        if self.status == "tool" and self.current_tool:
            return f"Running {self.current_tool}…"
        if self.status == "responding":
            return "Responding…"
        return "Thinking…"
