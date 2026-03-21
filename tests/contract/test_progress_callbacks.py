# tests/contract/test_progress_callbacks.py
"""Contract tests: every ProgressCallback × every ProgressEvent variant (4b).

When adding a new ProgressCallback implementation anywhere in the codebase,
register it in all_known_callbacks(). When adding a new event type to
callbacks.py, add it to ALL_EVENT_VARIANTS.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)
from nanobot.cli.progress import CliProgressHandler

ALL_EVENT_VARIANTS = [
    TextChunk(content="hello", streaming=False),
    TextChunk(content="hello", streaming=True),
    TextChunk(content=""),
    ToolCallEvent(tool_call_id="tc1", tool_name="read_file", args={"path": "/tmp"}),
    ToolResultEvent(tool_call_id="tc1", result="contents", tool_name="read_file"),
    DelegateStartEvent(delegation_id="d1", child_role="research", task_title="Find info"),
    DelegateEndEvent(delegation_id="d1", success=True),
    DelegateEndEvent(delegation_id="d1", success=False),
    StatusEvent(status_code="thinking"),
    StatusEvent(status_code="retrying"),
    StatusEvent(status_code="calling_tool"),
]


def all_known_callbacks() -> list[tuple[str, CliProgressHandler]]:
    """Registry of every ProgressCallback implementation in the codebase.
    Add new implementations here when they are created."""
    return [
        (
            "CliProgressHandler",
            CliProgressHandler(Console(file=StringIO()), channels_config=None),
        ),
    ]


@pytest.mark.parametrize(
    "name,callback",
    all_known_callbacks(),
    ids=lambda x: x if isinstance(x, str) else "",
)
@pytest.mark.parametrize("event", ALL_EVENT_VARIANTS, ids=repr)
async def test_callback_handles_all_event_variants(
    name: str, callback: CliProgressHandler, event: object
) -> None:
    """Every ProgressCallback must accept every ProgressEvent without raising."""
    await callback(event)  # type: ignore[arg-type]
