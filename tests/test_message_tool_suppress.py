"""Test message tool suppress logic for final replies."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")


class TestMessageToolSuppressLogic:
    """Final reply suppressed only when message tool sends to the same target."""

    @pytest.mark.asyncio
    async def test_suppress_when_sent_to_same_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Hello", "channel": "feishu", "chat_id": "chat123"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send")
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert result is None  # suppressed

    @pytest.mark.asyncio
    async def test_not_suppress_when_sent_to_different_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Email content", "channel": "email", "chat_id": "user@example.com"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="I've sent the email.", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send email")
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert sent[0].channel == "email"
        assert result is not None  # not suppressed
        assert result.channel == "feishu"

    @pytest.mark.asyncio
    async def test_not_suppress_when_no_message_tool_used(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Hello!", tool_calls=[]))
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        result = await loop._process_message(msg)

        assert result is not None
        assert "Hello" in result.content

    @pytest.mark.asyncio
    async def test_system_subagent_message_uses_structured_payload(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Wrapped up.", tool_calls=[]))
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="cli:direct",
            content="fallback text",
            metadata={
                "subagent_result": {
                    "type": "subagent_result",
                    "task_id": "sub-1",
                    "label": "report",
                    "task": "write report",
                    "status": "ok",
                    "summary": "Created ./report.md",
                    "artifacts": ["./report.md"],
                    "notes": [],
                    "error": None,
                }
            },
        )

        result = await loop._process_message(msg)

        assert result is not None
        assert result.content == "Wrapped up."
        provider_messages = loop.provider.chat_with_retry.await_args.kwargs["messages"]
        assert any("./report.md" in (item.get("content") or "") for item in provider_messages)

    @pytest.mark.asyncio
    async def test_process_direct_can_return_metadata(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop._process_message = AsyncMock(return_value=OutboundMessage(
            channel="cli",
            chat_id="direct",
            content="Done",
            metadata={"subagent_result": {"status": "ok"}},
        ))

        result = await loop.process_direct("hello", include_metadata=True)

        assert result == ("Done", {"subagent_result": {"status": "ok"}})

    @pytest.mark.asyncio
    async def test_spawn_to_subagent_result_metadata_chain(self, tmp_path: Path, monkeypatch) -> None:
        loop = _make_loop(tmp_path)

        calls = iter([
            LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(
                    id="call1",
                    name="spawn",
                    arguments={
                        "task": "write report",
                        "label": "report",
                        "goal": "summarize findings",
                        "constraints": ["do not modify code"],
                        "relevant_paths": ["./docs"],
                        "done_when": ["report file exists"],
                    },
                )],
            ),
            LLMResponse(content="Working on it.", tool_calls=[]),
            LLMResponse(content="Finished.", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))

        seen_spawn_kwargs: dict[str, object] = {}

        async def fake_spawn(**kwargs):
            seen_spawn_kwargs.update(kwargs)
            await loop.bus.publish_inbound(InboundMessage(
                channel="system",
                sender_id="subagent",
                chat_id="cli:direct",
                content="fallback text",
                metadata={
                    "subagent_result": {
                        "type": "subagent_result",
                        "task_id": "sub-1",
                        "label": "report",
                        "task": "write report",
                        "status": "ok",
                        "summary": "Created ./report.md",
                        "artifacts": ["./report.md"],
                        "notes": [],
                        "error": None,
                    }
                },
            ))
            return "Subagent [report] started."

        monkeypatch.setattr(loop.subagents, "spawn", fake_spawn)

        user_result = await loop._process_message(
            InboundMessage(channel="cli", sender_id="user1", chat_id="direct", content="Create a report")
        )
        assert user_result is not None
        assert user_result.content == "Working on it."
        assert seen_spawn_kwargs["goal"] == "summarize findings"
        assert seen_spawn_kwargs["constraints"] == ["do not modify code"]
        assert seen_spawn_kwargs["relevant_paths"] == ["./docs"]
        assert seen_spawn_kwargs["done_when"] == ["report file exists"]

        system_msg = await loop.bus.consume_inbound()
        system_result = await loop._process_message(system_msg)
        assert system_result is not None
        assert system_result.content == "Finished."

        final_messages = loop.provider.chat_with_retry.await_args_list[-1].kwargs["messages"]
        assert any("./report.md" in (item.get("content") or "") for item in final_messages)

    async def test_progress_hides_internal_reasoning(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(
                content="Visible<think>hidden</think>",
                tool_calls=[tool_call],
                reasoning_content="secret reasoning",
                thinking_blocks=[{"signature": "sig", "thought": "secret thought"}],
            ),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        progress: list[tuple[str, bool]] = []

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            progress.append((content, tool_hint))

        final_content, _, _ = await loop._run_agent_loop([], on_progress=on_progress)

        assert final_content == "Done"
        assert progress == [
            ("Visible", False),
            ('read_file("foo.txt")', True),
        ]


class TestMessageToolTurnTracking:

    def test_sent_in_turn_tracks_same_target(self) -> None:
        tool = MessageTool()
        tool.set_context("feishu", "chat1")
        assert not tool._sent_in_turn
        tool._sent_in_turn = True
        assert tool._sent_in_turn

    def test_start_turn_resets(self) -> None:
        tool = MessageTool()
        tool._sent_in_turn = True
        tool.start_turn()
        assert not tool._sent_in_turn
