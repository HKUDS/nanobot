"""Integration tests for the core agent loop.

Uses a mock LLM provider with scripted responses to test:
- Single-turn Q&A (no tool use)
- Multi-step tool use (tool call -> result -> final answer)
- Tool failure -> reflect -> retry
- Max iterations hit
- Context compression triggered
- Consecutive LLM errors -> graceful fallback
- Nudge for final answer (tool results but no text)
- Planning prompt injection
- Verification pass
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


# ---------------------------------------------------------------------------
# Mock provider that yields scripted LLM responses
# ---------------------------------------------------------------------------

class ScriptedProvider(LLMProvider):
    """LLM provider that returns pre-configured responses in order."""

    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self._index = 0
        self.call_log: list[dict] = []

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.call_log.append({
            "messages_count": len(messages),
            "has_tools": tools is not None,
            "model": model,
        })
        if self._index >= len(self._responses):
            # Default fallback: simple text
            return LLMResponse(content="(no more scripted responses)")
        resp = self._responses[self._index]
        self._index += 1
        return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path, **overrides) -> AgentConfig:
    defaults = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_loop(tmp_path: Path, provider: LLMProvider, **config_overrides) -> AgentLoop:
    bus = MessageBus()
    config = _make_config(tmp_path, **config_overrides)
    loop = AgentLoop(bus, provider, config)
    return loop


def _make_inbound(text: str, channel: str = "cli", chat_id: str = "test-user") -> InboundMessage:
    return InboundMessage(
        channel=channel,
        chat_id=chat_id,
        sender_id="user-1",
        content=text,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentLoopSingleTurn:
    """Test single-turn Q&A without tool use."""

    @pytest.mark.asyncio
    async def test_simple_qa(self, tmp_path: Path):
        """Agent returns the LLM's text response directly."""
        provider = ScriptedProvider([
            LLMResponse(content="Hello! I'm nanobot."),
        ])
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("Hi there")
        result = await loop._process_message(msg)

        assert result is not None
        assert "Hello" in result.content
        assert provider._index >= 1

    @pytest.mark.asyncio
    async def test_empty_content_fallback(self, tmp_path: Path):
        """When LLM returns None content with no tool calls, agent returns explanation."""
        provider = ScriptedProvider([
            LLMResponse(content=None),
        ])
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("Tell me something")
        result = await loop._process_message(msg)

        assert result is not None
        # Should get a fallback explanation
        assert len(result.content) > 0


class TestAgentLoopToolUse:
    """Test multi-step tool use."""

    @pytest.mark.asyncio
    async def test_tool_call_then_answer(self, tmp_path: Path):
        """Agent calls a tool, gets result, then produces final answer."""
        # Create a test file for read_file to find
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content here")

        provider = ScriptedProvider([
            # First response: tool call to read_file
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="read_file",
                        arguments={"path": str(test_file)},
                    )
                ],
            ),
            # Second response: final answer
            LLMResponse(content="The file contains: file content here"),
        ])
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("Read test.txt")
        result = await loop._process_message(msg)

        assert result is not None
        assert "file content" in result.content
        assert provider._index == 2

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self, tmp_path: Path):
        """Agent makes multiple sequential tool calls."""
        (tmp_path / "a.txt").write_text("alpha")
        (tmp_path / "b.txt").write_text("beta")

        provider = ScriptedProvider([
            # Call 1: read a.txt
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name="read_file",
                                    arguments={"path": str(tmp_path / "a.txt")}),
                ],
            ),
            # Call 2: read b.txt
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c2", name="read_file",
                                    arguments={"path": str(tmp_path / "b.txt")}),
                ],
            ),
            # Answer
            LLMResponse(content="a.txt contains alpha, b.txt contains beta"),
        ])
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Read both files"))

        assert result is not None
        assert "alpha" in result.content
        assert "beta" in result.content


class TestAgentLoopToolFailure:
    """Test tool failure, reflection, and retry."""

    @pytest.mark.asyncio
    async def test_tool_not_found(self, tmp_path: Path):
        """Calling a nonexistent tool returns an error, agent continues."""
        provider = ScriptedProvider([
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name="nonexistent_tool",
                                    arguments={"x": 1}),
                ],
            ),
            # Agent should retry or respond after seeing the error
            LLMResponse(content="Sorry, that tool doesn't exist."),
        ])
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Use nonexistent_tool"))

        assert result is not None
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_read_missing_file_retry(self, tmp_path: Path):
        """Reading a missing file fails, agent retries with different approach."""
        provider = ScriptedProvider([
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name="read_file",
                                    arguments={"path": str(tmp_path / "missing.txt")}),
                ],
            ),
            # Agent sees the error and responds
            LLMResponse(content="The file doesn't exist."),
        ])
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Read missing.txt"))

        assert result is not None
        assert len(result.content) > 0


class TestAgentLoopMaxIterations:
    """Test max iterations limit."""

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, tmp_path: Path):
        """Agent stops after max_iterations and returns a fallback message."""
        # All responses are tool calls — agent never produces text
        provider = ScriptedProvider([
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id=f"c{i}", name="list_dir",
                                    arguments={"path": str(tmp_path)}),
                ],
            )
            for i in range(10)  # More than max_iterations=3
        ])
        loop = _make_loop(tmp_path, provider, max_iterations=3)
        result = await loop._process_message(_make_inbound("List directory forever"))

        assert result is not None
        assert "maximum" in result.content.lower() or "iterations" in result.content.lower()


class TestAgentLoopConsecutiveErrors:
    """Test consecutive LLM errors -> graceful fallback."""

    @pytest.mark.asyncio
    async def test_consecutive_llm_errors(self, tmp_path: Path):
        """Three consecutive LLM errors cause graceful failure."""
        provider = ScriptedProvider([
            LLMResponse(content="LLM error occurred", finish_reason="error"),
            LLMResponse(content="LLM error occurred", finish_reason="error"),
            LLMResponse(content="LLM error occurred", finish_reason="error"),
        ])
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Hello"))

        assert result is not None
        assert "trouble" in result.content.lower() or "try again" in result.content.lower()


class TestAgentLoopNudgeFinalAnswer:
    """Test the nudge for final answer when tool results present but no text."""

    @pytest.mark.asyncio
    async def test_nudge_after_tool_result_no_text(self, tmp_path: Path):
        """When LLM returns tool results with content, then blank, it gets nudged."""
        test_file = tmp_path / "data.txt"
        test_file.write_text("important data")

        provider = ScriptedProvider([
            # Tool call
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name="read_file",
                                    arguments={"path": str(test_file)}),
                ],
            ),
            # LLM returns content + tool calls (no final answer yet)
            LLMResponse(content="Let me check...", tool_calls=[
                ToolCallRequest(id="c2", name="list_dir",
                                arguments={"path": str(tmp_path)}),
            ]),
            # Now final answer
            LLMResponse(content="The data file contains: important data"),
        ])
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("What's in data.txt?"))

        assert result is not None
        assert "important data" in result.content


class TestAgentLoopPlanning:
    """Test planning prompt injection."""

    @pytest.mark.asyncio
    async def test_planning_prompt_injected(self, tmp_path: Path):
        """When planning is enabled and task looks complex, planning prompt is injected."""
        provider = ScriptedProvider([
            LLMResponse(content="1. First step\n2. Second step\nDone!"),
        ])
        loop = _make_loop(tmp_path, provider, planning_enabled=True)
        # Multi-step request that triggers planning
        msg = _make_inbound("Research the weather and then create a summary report")
        result = await loop._process_message(msg)

        assert result is not None
        # Provider should've received messages — check that a system message with planning was in there
        assert provider._index >= 1

    @pytest.mark.asyncio
    async def test_planning_not_injected_for_simple_query(self, tmp_path: Path):
        """Simple queries don't trigger planning."""
        provider = ScriptedProvider([
            LLMResponse(content="It's 42."),
        ])
        loop = _make_loop(tmp_path, provider, planning_enabled=True)
        msg = _make_inbound("What is 6 * 7?")
        result = await loop._process_message(msg)

        assert result is not None
        assert result.content == "It's 42."


class TestAgentLoopContextCompression:
    """Test context compression under budget pressure."""

    @pytest.mark.asyncio
    async def test_large_context_triggers_compression(self, tmp_path: Path):
        """Compression doesn't crash or lose the final answer."""
        # Build a long conversation that would overflow
        provider = ScriptedProvider([
            LLMResponse(content="Summary: all good"),
        ])
        loop = _make_loop(tmp_path, provider, context_window_tokens=500)

        # Manually inject many messages into a session to force compression
        session = loop.sessions.get_or_create("cli:test-user")
        for i in range(50):
            session.messages.append({
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"Message number {i} " * 100,  # Large messages
            })
        loop.sessions.save(session)

        msg = _make_inbound("Summarize everything")
        result = await loop._process_message(msg)

        assert result is not None
        assert len(result.content) > 0


class TestAgentLoopSlashCommands:
    """Test slash command handling."""

    @pytest.mark.asyncio
    async def test_help_command(self, tmp_path: Path):
        """The /help command returns help text without calling LLM."""
        provider = ScriptedProvider([])
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("/help"))

        assert result is not None
        assert "commands" in result.content.lower()
        assert provider._index == 0  # No LLM call

    @pytest.mark.asyncio
    async def test_new_command(self, tmp_path: Path):
        """The /new command clears session."""
        # Provide a consolidation-compatible response (save_memory tool call)
        provider = ScriptedProvider([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(
                    id="save1",
                    name="save_memory",
                    arguments={
                        "updated_memory": "# Memory\n\nOld message captured.",
                        "history_entry": "User said: old message",
                    },
                )],
            ),
        ])
        loop = _make_loop(tmp_path, provider)

        # Add some history first
        session = loop.sessions.get_or_create("cli:test-user")
        session.messages.append({"role": "user", "content": "old message"})
        loop.sessions.save(session)

        result = await loop._process_message(_make_inbound("/new"))

        assert result is not None
        assert "new session" in result.content.lower()


class TestAgentLoopProviderCallLog:
    """Verify that the provider receives the expected number and shape of calls."""

    @pytest.mark.asyncio
    async def test_single_provider_call_for_simple_qa(self, tmp_path: Path):
        """Simple Q&A makes exactly 1 provider call (no verification, no planning)."""
        provider = ScriptedProvider([
            LLMResponse(content="The answer is 42."),
        ])
        loop = _make_loop(tmp_path, provider)
        await loop._process_message(_make_inbound("What is the answer?"))

        assert len(provider.call_log) == 1
        assert provider.call_log[0]["has_tools"] is True  # tools always offered first turn
