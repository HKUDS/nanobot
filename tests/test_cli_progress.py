# tests/test_cli_progress.py
"""Unit tests for CliProgressHandler (4a).

Tests the handler in complete isolation — no CLI stack, no agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from typing import cast

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
from nanobot.config.schema import ChannelsConfig


@dataclass
class _FakeChannelsConfig:
    """Minimal stub for ChannelsConfig in tests.

    Only includes the fields that CliProgressHandler actually uses.
    """

    send_progress: bool = True
    send_tool_hints: bool = True


def _handler(
    send_progress: bool = True, send_tool_hints: bool = True
) -> tuple[CliProgressHandler, StringIO]:
    buf = StringIO()
    fake_config = _FakeChannelsConfig(send_progress=send_progress, send_tool_hints=send_tool_hints)
    # Cast to ChannelsConfig since we only use send_progress and send_tool_hints
    ch = cast(ChannelsConfig, fake_config)
    return CliProgressHandler(Console(file=buf, highlight=False), channels_config=ch), buf


async def test_text_chunk_printed() -> None:
    h, buf = _handler()
    await h(TextChunk(content="hello"))
    assert "hello" in buf.getvalue()


async def test_text_chunk_suppressed_when_send_progress_off() -> None:
    h, buf = _handler(send_progress=False)
    await h(TextChunk(content="hello"))
    assert buf.getvalue() == ""


async def test_empty_text_chunk_produces_no_output() -> None:
    h, buf = _handler()
    await h(TextChunk(content=""))
    assert buf.getvalue() == ""


async def test_tool_call_printed_when_hints_on() -> None:
    h, buf = _handler(send_tool_hints=True)
    await h(ToolCallEvent(tool_call_id="tc1", tool_name="read_file", args={}))
    assert "read_file" in buf.getvalue()


async def test_tool_call_suppressed_when_hints_off() -> None:
    h, buf = _handler(send_tool_hints=False)
    await h(ToolCallEvent(tool_call_id="tc1", tool_name="read_file", args={}))
    assert buf.getvalue() == ""


async def test_no_channels_config_prints_text() -> None:
    """Without channels_config, handler defaults to printing everything."""
    buf = StringIO()
    h = CliProgressHandler(Console(file=buf, highlight=False), channels_config=None)
    await h(TextChunk(content="hi there"))
    assert "hi there" in buf.getvalue()


async def test_no_channels_config_prints_tool_calls() -> None:
    buf = StringIO()
    h = CliProgressHandler(Console(file=buf, highlight=False), channels_config=None)
    await h(ToolCallEvent(tool_call_id="tc1", tool_name="list_dir", args={}))
    assert "list_dir" in buf.getvalue()


async def test_status_event_silent() -> None:
    h, buf = _handler()
    await h(StatusEvent(status_code="retrying"))
    assert buf.getvalue() == ""


async def test_tool_result_event_silent() -> None:
    h, buf = _handler()
    await h(ToolResultEvent(tool_call_id="tc1", result="ok", tool_name="read_file"))
    assert buf.getvalue() == ""


async def test_delegate_start_event_silent() -> None:
    h, buf = _handler()
    await h(DelegateStartEvent(delegation_id="d1", child_role="research"))
    assert buf.getvalue() == ""


async def test_delegate_end_event_silent() -> None:
    h, buf = _handler()
    await h(DelegateEndEvent(delegation_id="d1", success=True))
    assert buf.getvalue() == ""
