"""Scratchpad read/write tools for multi-agent artifact sharing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from nanobot.agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from nanobot.agent.scratchpad import Scratchpad


class ScratchpadWriteTool(Tool):
    """Write an artifact to the session scratchpad."""

    readonly = False

    def __init__(self, scratchpad: Scratchpad) -> None:
        self._scratchpad = scratchpad

    name = "write_scratchpad"
    description = "Write a labeled artifact to the session scratchpad for other agents to read."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "description": "Short label for the entry.",
            },
            "content": {
                "type": "string",
                "description": "Content to store.",
            },
        },
        "required": ["label", "content"],
    }

    async def execute(self, *, label: str, content: str, **_: Any) -> ToolResult:  # type: ignore[override]
        entry_id = await self._scratchpad.write(
            role="agent",
            label=label,
            content=content,
        )
        return ToolResult.ok(f"Written to scratchpad as [{entry_id}]")


class ScratchpadReadTool(Tool):
    """Read entries from the session scratchpad."""

    readonly = True

    def __init__(self, scratchpad: Scratchpad) -> None:
        self._scratchpad = scratchpad

    name = "read_scratchpad"
    description = "Read entries from the session scratchpad. Omit entry_id to list all entries."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": "Optional entry ID to read a specific entry.",
            },
        },
    }

    async def execute(self, *, entry_id: str = "", **_: Any) -> ToolResult:  # type: ignore[override]
        result = self._scratchpad.read(entry_id or None)
        if result is None:
            if entry_id:
                return ToolResult.ok(f"Entry {entry_id} not found.")
            return ToolResult.ok("Scratchpad is empty.")
        return ToolResult.ok(result)
