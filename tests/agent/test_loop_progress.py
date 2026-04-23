"""Tests for structured tool-event progress metadata emitted by AgentLoop."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")


class TestToolEventProgress:
    """_run_agent_loop emits structured tool_events via on_progress."""

    @pytest.mark.asyncio
    async def test_start_and_finish_events_emitted(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="custom_tool", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="Visible", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.prepare_call = MagicMock(return_value=(None, {"path": "foo.txt"}, None))
        loop.tools.execute = AsyncMock(return_value="ok")

        progress: list[tuple[str, bool, list[dict] | None]] = []

        async def on_progress(
            content: str,
            *,
            tool_hint: bool = False,
            tool_events: list[dict] | None = None,
        ) -> None:
            progress.append((content, tool_hint, tool_events))

        final_content, _, _, _, _ = await loop._run_agent_loop([], on_progress=on_progress)

        assert final_content == "Done"
        assert progress == [
            ("Visible", False, None),
            (
                'custom_tool("foo.txt")',
                True,
                [{
                    "version": 1,
                    "phase": "start",
                    "call_id": "call1",
                    "name": "custom_tool",
                    "arguments": {"path": "foo.txt"},
                    "result": None,
                    "error": None,
                    "files": [],
                    "embeds": [],
                }],
            ),
            (
                "",
                False,
                [{
                    "version": 1,
                    "phase": "end",
                    "call_id": "call1",
                    "name": "custom_tool",
                    "arguments": {"path": "foo.txt"},
                    "result": "ok",
                    "error": None,
                    "files": [],
                    "embeds": [],
                }],
            ),
        ]

    @pytest.mark.asyncio
    async def test_bus_progress_forwards_tool_events_to_outbound_metadata(self, tmp_path: Path) -> None:
        """When run() handles a bus message, _tool_events lands in OutboundMessage metadata."""
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

        tool_call = ToolCallRequest(id="tc1", name="exec", arguments={"command": "ls"})
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.prepare_call = MagicMock(return_value=(None, {"command": "ls"}, None))
        loop.tools.execute = AsyncMock(return_value="file.txt")

        msg = InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat1",
            content="run ls",
        )
        await loop._dispatch(msg)

        # Drain all outbound messages and find the one carrying _tool_events
        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        tool_event_msgs = [m for m in outbound if m.metadata and m.metadata.get("_tool_events")]
        assert tool_event_msgs, "expected at least one outbound message with _tool_events"

        start_msgs = [m for m in tool_event_msgs if m.metadata["_tool_events"][0]["phase"] == "start"]
        finish_msgs = [m for m in tool_event_msgs if m.metadata["_tool_events"][0]["phase"] in ("end", "error")]
        assert start_msgs, "expected a start-phase tool event"
        assert finish_msgs, "expected a finish-phase tool event"

        start = start_msgs[0].metadata["_tool_events"][0]
        assert start["name"] == "exec"
        assert start["call_id"] == "tc1"
        assert start["result"] is None

        finish = finish_msgs[0].metadata["_tool_events"][0]
        assert finish["phase"] == "end"
        assert finish["result"] == "file.txt"
