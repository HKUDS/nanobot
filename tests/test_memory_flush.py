"""Tests for memory flush, compaction, and token estimation."""

import json
import pytest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from dataclasses import dataclass, field

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.config.schema import MemoryConfig


# ============================================================================
# Fake provider for testing
# ============================================================================


class FakeProvider(LLMProvider):
    """A fake LLM provider that returns pre-configured responses."""

    def __init__(self, responses=None):
        super().__init__(api_key="fake")
        self._responses = responses or []
        self._call_index = 0
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None, model=None, **kwargs) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "model": model})
        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
            self._call_index += 1
            return resp
        return LLMResponse(content="Default response")

    def get_default_model(self) -> str:
        return "fake-model"


def _make_agent(workspace, responses=None, memory_config=None):
    """Create an AgentLoop with fake provider for testing."""
    bus = MessageBus()
    provider = FakeProvider(responses=responses)
    config = memory_config or MemoryConfig(
        max_context_tokens=1000,
        flush_threshold_ratio=0.75,
        compact_keep_recent=3,
    )
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        memory_config=config,
    )
    return agent, provider


# ============================================================================
# Token estimation
# ============================================================================


def test_estimate_tokens_simple(workspace):
    """Token estimation uses chars // 4 when tiktoken unavailable."""
    agent, _ = _make_agent(workspace)

    messages = [
        {"role": "system", "content": "a" * 400},  # 100 tokens
        {"role": "user", "content": "b" * 200},     # 50 tokens
    ]
    with patch.object(AgentLoop, "_get_tokenizer", return_value=None):
        estimated = agent._estimate_tokens(messages)
    assert estimated == 150


def test_estimate_tokens_multimodal(workspace):
    """Only text parts of multimodal content are counted."""
    agent, _ = _make_agent(workspace)

    messages = [
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "text", "text": "x" * 80},
        ]},
    ]
    with patch.object(AgentLoop, "_get_tokenizer", return_value=None):
        estimated = agent._estimate_tokens(messages)
    assert estimated == 20  # 80 chars // 4


def test_estimate_tokens_empty(workspace):
    """Empty messages return 0."""
    agent, _ = _make_agent(workspace)
    assert agent._estimate_tokens([]) == 0


def test_estimate_tokens_with_tiktoken(workspace):
    """When tiktoken is available, uses accurate token counting."""
    agent, _ = _make_agent(workspace)

    # Create a mock tokenizer
    mock_enc = MagicMock()
    mock_enc.encode.return_value = list(range(42))  # 42 tokens

    with patch.object(AgentLoop, "_get_tokenizer", return_value=mock_enc):
        messages = [{"role": "user", "content": "Hello world"}]
        result = agent._estimate_tokens(messages)

    assert result == 42
    mock_enc.encode.assert_called_once()


def test_estimate_tokens_fallback_without_tiktoken(workspace):
    """When tiktoken is unavailable, falls back to chars // 4."""
    agent, _ = _make_agent(workspace)

    with patch.object(AgentLoop, "_get_tokenizer", return_value=None):
        messages = [{"role": "user", "content": "a" * 80}]
        result = agent._estimate_tokens(messages)

    assert result == 20  # 80 chars // 4


# ============================================================================
# Flush trigger condition
# ============================================================================


def test_should_flush_below_threshold(workspace):
    """Below 75% of max tokens, no flush needed."""
    agent, _ = _make_agent(workspace, memory_config=MemoryConfig(
        max_context_tokens=1000, flush_threshold_ratio=0.75,
    ))
    # 700 tokens < 750 threshold (using chars // 4 fallback)
    messages = [{"role": "user", "content": "a" * 2800}]
    with patch.object(AgentLoop, "_get_tokenizer", return_value=None):
        assert agent._should_flush(messages) is False


def test_should_flush_above_threshold(workspace):
    """Above 75% of max tokens, flush is triggered."""
    agent, _ = _make_agent(workspace, memory_config=MemoryConfig(
        max_context_tokens=1000, flush_threshold_ratio=0.75,
    ))
    # 800 tokens > 750 threshold (using chars // 4 fallback)
    messages = [{"role": "user", "content": "a" * 3200}]
    with patch.object(AgentLoop, "_get_tokenizer", return_value=None):
        assert agent._should_flush(messages) is True


# ============================================================================
# Memory flush
# ============================================================================


async def test_memory_flush_calls_tools(workspace):
    """Memory flush executes tool calls from the LLM response."""
    # LLM responds with a write_file tool call, then DONE
    tool_response = LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(
            id="call_1",
            name="write_file",
            arguments={"path": str(workspace / "memory" / "flush_test.md"), "content": "flushed"},
        )],
    )
    done_response = LLMResponse(content="DONE")

    agent, provider = _make_agent(workspace, responses=[tool_response, done_response])

    messages = [{"role": "system", "content": "test"}]
    await agent._memory_flush(messages)

    # Provider should have been called (flush conversation)
    assert len(provider.calls) >= 1

    # The write_file tool should have been executed
    flush_file = workspace / "memory" / "flush_test.md"
    assert flush_file.exists()
    assert flush_file.read_text() == "flushed"


async def test_memory_flush_multiple_tool_calls(workspace):
    """Multiple tool calls in one response produce a single assistant message."""
    tool_response = LLMResponse(
        content="Saving memories...",
        tool_calls=[
            ToolCallRequest(
                id="call_1",
                name="write_file",
                arguments={"path": str(workspace / "memory" / "file1.md"), "content": "one"},
            ),
            ToolCallRequest(
                id="call_2",
                name="write_file",
                arguments={"path": str(workspace / "memory" / "file2.md"), "content": "two"},
            ),
        ],
    )
    done_response = LLMResponse(content="DONE")

    agent, provider = _make_agent(workspace, responses=[tool_response, done_response])

    messages = [{"role": "system", "content": "test"}]
    await agent._memory_flush(messages)

    # Both files should be written
    assert (workspace / "memory" / "file1.md").read_text() == "one"
    assert (workspace / "memory" / "file2.md").read_text() == "two"

    # Inspect flush_messages passed to the second provider call
    second_call_messages = provider.calls[1]["messages"]
    # Find all assistant messages appended during flush (after the user system message)
    assistant_msgs = [m for m in second_call_messages if m.get("role") == "assistant"
                      and "tool_calls" in m]
    # There should be exactly ONE assistant message with both tool calls
    assert len(assistant_msgs) == 1
    assert len(assistant_msgs[0]["tool_calls"]) == 2

    # Tool results should follow as separate messages
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert {m["tool_call_id"] for m in tool_msgs} == {"call_1", "call_2"}


async def test_memory_flush_no_tools(workspace):
    """Flush completes gracefully when LLM responds without tool calls."""
    done_response = LLMResponse(content="DONE")
    agent, provider = _make_agent(workspace, responses=[done_response])

    messages = [{"role": "system", "content": "test"}]
    await agent._memory_flush(messages)

    assert len(provider.calls) == 1


# ============================================================================
# Compaction
# ============================================================================


async def test_compact_history_basic(workspace):
    """Compaction compresses old messages, keeps system + summary + recent."""
    summary_response = LLMResponse(content="User discussed Python and Docker setup.")

    agent, _ = _make_agent(
        workspace,
        responses=[summary_response],
        memory_config=MemoryConfig(compact_keep_recent=3),
    )

    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Old message 1"},
        {"role": "assistant", "content": "Old response 1"},
        {"role": "user", "content": "Old message 2"},
        {"role": "assistant", "content": "Old response 2"},
        {"role": "user", "content": "Recent 1"},
        {"role": "assistant", "content": "Recent 2"},
        {"role": "user", "content": "Recent 3"},
    ]

    compacted = await agent._compact_history(messages)

    # Structure: system + summary + 3 recent
    assert len(compacted) == 5
    assert compacted[0]["role"] == "system"
    assert compacted[0]["content"] == "System prompt"
    assert "[Previous conversation summary]" in compacted[1]["content"]
    assert "Python" in compacted[1]["content"]
    # Last 3 messages preserved
    assert compacted[2]["content"] == "Recent 1"
    assert compacted[3]["content"] == "Recent 2"
    assert compacted[4]["content"] == "Recent 3"


async def test_compact_history_too_few_messages(workspace):
    """When messages are fewer than keep_recent, no compaction happens."""
    agent, provider = _make_agent(
        workspace,
        memory_config=MemoryConfig(compact_keep_recent=10),
    )

    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]

    compacted = await agent._compact_history(messages)

    # Should be unchanged
    assert compacted == messages
    # Provider should not have been called
    assert len(provider.calls) == 0


async def test_compact_preserves_system_prompt(workspace):
    """System prompt is always preserved after compaction."""
    summary_response = LLMResponse(content="Summary of conversation.")

    agent, _ = _make_agent(
        workspace,
        responses=[summary_response],
        memory_config=MemoryConfig(compact_keep_recent=2),
    )

    system_content = "You are nanobot, a helpful assistant."
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "msg1"},
        {"role": "assistant", "content": "resp1"},
        {"role": "user", "content": "msg2"},
        {"role": "assistant", "content": "resp2"},
    ]

    compacted = await agent._compact_history(messages)

    assert compacted[0]["role"] == "system"
    assert compacted[0]["content"] == system_content


async def test_compact_history_summary_none(workspace):
    """Compaction handles LLM returning content=None gracefully."""
    summary_response = LLMResponse(content=None)  # e.g. LLM only returned tool calls

    agent, _ = _make_agent(
        workspace,
        responses=[summary_response],
        memory_config=MemoryConfig(compact_keep_recent=2),
    )

    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Old message 1"},
        {"role": "assistant", "content": "Old response 1"},
        {"role": "user", "content": "Recent 1"},
        {"role": "assistant", "content": "Recent 2"},
    ]

    compacted = await agent._compact_history(messages)

    # Should not contain literal "None" string
    summary_msg = compacted[1]
    assert "[Previous conversation summary]" in summary_msg["content"]
    assert "None" not in summary_msg["content"]
    assert "No summary available." in summary_msg["content"]


async def test_compact_history_recent_starts_with_tool(workspace):
    """When keep boundary falls inside a tool call sequence, recent is adjusted."""
    summary_response = LLMResponse(content="Summary of old messages.")

    agent, provider = _make_agent(
        workspace,
        responses=[summary_response],
        memory_config=MemoryConfig(compact_keep_recent=3),
    )

    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Old message"},
        {"role": "assistant", "content": "Old response"},
        {"role": "user", "content": "What file is this?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "tc1", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}},
        ]},
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "print('hi')"},  # <-- would be recent[0] with keep=3
        {"role": "assistant", "content": "The file prints hi."},
        {"role": "user", "content": "Thanks"},
    ]

    compacted = await agent._compact_history(messages)

    # The recent portion must NOT start with a tool message
    recent_start = 2  # after system_prompt + summary
    assert compacted[recent_start]["role"] != "tool"
    # All roles in the result should be valid sequence
    roles = [m["role"] for m in compacted]
    for i, role in enumerate(roles):
        if role == "tool":
            # A tool message must be preceded by an assistant message (possibly
            # with other tool messages in between for the same assistant turn)
            prev_roles = roles[:i]
            assert "assistant" in prev_roles


async def test_compact_history_filters_tool_messages_for_summarizer(workspace):
    """Summarizer does not receive tool role or assistant tool_calls messages."""
    summary_response = LLMResponse(content="Summary.")

    agent, provider = _make_agent(
        workspace,
        responses=[summary_response],
        memory_config=MemoryConfig(compact_keep_recent=2),
    )

    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Read file x.py"},
        {"role": "assistant", "content": "Reading...", "tool_calls": [
            {"id": "tc1", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}},
        ]},
        {"role": "tool", "tool_call_id": "tc1", "name": "read_file", "content": "print('hi')"},
        {"role": "assistant", "content": "The file contains a print statement."},
        {"role": "user", "content": "Recent 1"},
        {"role": "assistant", "content": "Recent 2"},
    ]

    compacted = await agent._compact_history(messages)

    # Inspect what was sent to the summarizer
    summarizer_call = provider.calls[0]
    summarizer_messages = summarizer_call["messages"]

    # No tool role messages should be in the summarizer input
    for msg in summarizer_messages:
        assert msg["role"] != "tool", f"Found tool message in summarizer input: {msg}"
        if msg["role"] == "assistant":
            assert "tool_calls" not in msg, f"Found tool_calls in assistant message: {msg}"


# ============================================================================
# Integration: flush triggers before compaction in agent loop
# ============================================================================


async def test_flush_then_compact_in_loop(workspace):
    """When context exceeds threshold, flush and compact are triggered."""
    # Create a memory config with very low threshold to trigger flush
    config = MemoryConfig(
        max_context_tokens=100,  # very low
        flush_threshold_ratio=0.5,  # 50 tokens triggers flush
        compact_keep_recent=2,
    )

    # Responses: flush DONE, compact summary, then final answer
    responses = [
        LLMResponse(content="DONE"),                          # flush response
        LLMResponse(content="Summary of old conversation."),  # compact summary
        LLMResponse(content="Here is my answer."),            # actual response
    ]

    agent, provider = _make_agent(workspace, responses=responses, memory_config=config)

    # Build messages that exceed the threshold
    # System prompt + long history
    from nanobot.bus.events import InboundMessage
    from nanobot.session.manager import Session

    # Pre-populate session with long history
    session = agent.sessions.get_or_create("cli:test")
    for i in range(20):
        session.add_message("user", f"Message {i} " + "x" * 100)
        session.add_message("assistant", f"Response {i} " + "y" * 100)

    msg = InboundMessage(
        channel="cli", sender_id="user", chat_id="test",
        content="What did we discuss?",
    )

    response = await agent._process_message(msg)

    # Should have gotten a response (the final answer)
    assert response is not None
    assert response.content == "Here is my answer."

    # Provider should have been called multiple times (flush + compact + answer)
    assert len(provider.calls) >= 2
