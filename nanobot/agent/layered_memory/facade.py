"""Layered memory facade — single entry point for loop/runner integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanobot.config.schema import LayeredMemoryConfig


@dataclass(frozen=True)
class RecallResult:
    """Turn-before recall payload merged into runtime / system prompt."""

    prepend_lines: list[str] = field(default_factory=list)
    append_system: str | None = None


class LayeredMemoryFacade:
    """Coordinates offload (canvas), capture (L0), recall, and pipeline hooks.

    LM0-C: no-op stubs with config short-circuit. LM1+ fill in submodules.
    """

    __slots__ = ("_config", "_workspace")

    def __init__(self, workspace: Path, config: LayeredMemoryConfig | None = None) -> None:
        self._workspace = workspace
        self._config = config or LayeredMemoryConfig()

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def config(self) -> LayeredMemoryConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        """Master switch (``layeredMemory.enable``)."""
        return self._config.enable

    async def recall(
        self,
        query: str,
        session_key: str,
        *,
        is_subagent: bool = False,
    ) -> RecallResult:
        """L1/L2/L3 recall before ``build_messages`` (LM2)."""
        if not self._config.recall_enabled(is_subagent=is_subagent):
            return RecallResult()
        _ = query, session_key
        return RecallResult()

    def canvas_lines(self, session_key: str, *, is_subagent: bool = False) -> list[str]:
        """Task canvas Mermaid lines for runtime injection (LM1)."""
        if not self._config.offload_enabled(is_subagent=is_subagent):
            return []
        _ = session_key
        return []

    async def capture_turn(
        self,
        session_key: str,
        new_messages: list[dict[str, Any]],
        *,
        is_subagent: bool = False,
    ) -> None:
        """Persist L0 slice and notify pipeline after ``_save_turn`` (LM2)."""
        if not self._config.capture_enabled(is_subagent=is_subagent):
            return
        _ = session_key, new_messages

    def register_tool_result(
        self,
        *,
        session_key: str,
        node_id: str,
        tool_name: str,
        persist_path: str | None,
        summary: str,
        chars: int,
        is_subagent: bool = False,
    ) -> None:
        """Register a tool result node after normalize/persist (LM1)."""
        if not self._config.offload_enabled(is_subagent=is_subagent):
            return
        _ = session_key, node_id, tool_name, persist_path, summary, chars
