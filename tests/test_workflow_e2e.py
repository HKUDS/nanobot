"""End-to-end workflow tests for the agent processing pipeline.

These tests exercise full request flows through the agent loop:
- Inbound message → context assembly → LLM → tool execution → response
- Memory event storage → subsequent retrieval
- Error handling and graceful degradation

Uses ScriptedProvider with full message capture to verify the entire
orchestration chain, not just individual components.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from tests.helpers import ScriptedProvider

# ---------------------------------------------------------------------------
# Helpers (same pattern as golden tests)
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_loop(tmp_path: Path, provider: LLMProvider, **config_overrides: Any) -> AgentLoop:
    bus = MessageBus()
    config = _make_config(tmp_path, **config_overrides)
    return AgentLoop(bus, provider, config)


def _make_inbound(text: str) -> InboundMessage:
    return InboundMessage(
        channel="cli",
        chat_id="workflow-test",
        sender_id="user-1",
        content=text,
    )


# ---------------------------------------------------------------------------
# Workflow 1: Full pipeline — user question → tool → answer
# ---------------------------------------------------------------------------


class TestWorkflowFullPipeline:
    """Complete pipeline: user asks a question requiring a tool call,
    agent uses tool, gets result, formulates answer.
    """

    async def test_question_tool_answer_pipeline(self, tmp_path: Path):
        """User asks about workspace → agent lists dir → answers."""
        (tmp_path / "README.md").write_text("# My Project")
        (tmp_path / "main.py").write_text("print('hello')")

        provider = ScriptedProvider(
            [
                # LLM decides to list directory
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="list_dir",
                            arguments={"path": str(tmp_path)},
                        )
                    ],
                ),
                # LLM produces final answer
                LLMResponse(content="The workspace contains README.md and main.py."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("What files are here?"))

        assert result is not None
        assert "README" in result.content or "main" in result.content
        assert len(provider.call_log) == 2

    async def test_write_then_read_pipeline(self, tmp_path: Path):
        """Agent writes a file then reads it back to confirm."""
        target = tmp_path / "output.txt"
        provider = ScriptedProvider(
            [
                # Step 1: write
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="write_file",
                            arguments={"path": str(target), "content": "hello world"},
                        )
                    ],
                ),
                # Step 2: read back
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc2",
                            name="read_file",
                            arguments={"path": str(target)},
                        )
                    ],
                ),
                # Step 3: confirm
                LLMResponse(content="File written and verified."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Create and verify output.txt"))

        assert result is not None
        assert target.exists()
        assert target.read_text() == "hello world"


# ---------------------------------------------------------------------------
# Workflow 2: Context carries system prompt and session history
# ---------------------------------------------------------------------------


class TestWorkflowContextAssembly:
    """Verify the agent assembles proper context including system prompt."""

    async def test_system_prompt_always_present(self, tmp_path: Path):
        provider = ScriptedProvider([LLMResponse(content="Hi!")])
        loop = _make_loop(tmp_path, provider)
        await loop._process_message(_make_inbound("Hello"))

        messages = provider.call_log[0]["messages"]
        assert messages[0]["role"] == "system"
        assert len(messages[0]["content"]) > 0, "System prompt must not be empty"

    async def test_user_message_forwarded(self, tmp_path: Path):
        provider = ScriptedProvider([LLMResponse(content="Response")])
        loop = _make_loop(tmp_path, provider)
        await loop._process_message(_make_inbound("What is 2+2?"))

        messages = provider.call_log[0]["messages"]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert any("2+2" in str(m.get("content", "")) for m in user_msgs)

    async def test_tools_offered_to_llm(self, tmp_path: Path):
        provider = ScriptedProvider([LLMResponse(content="Done")])
        loop = _make_loop(tmp_path, provider)
        await loop._process_message(_make_inbound("do something"))

        # Agent should offer tool definitions on the first call
        assert provider.call_log[0]["tools"] is not None
        assert len(provider.call_log[0]["tools"]) > 0


# ---------------------------------------------------------------------------
# Workflow 3: Graceful handling of LLM exceptions
# ---------------------------------------------------------------------------


class TestWorkflowErrorHandling:
    """Agent must handle provider errors gracefully."""

    def test_user_friendly_error_mapping(self):
        """_user_friendly_error maps known exception patterns to helpful messages."""
        from nanobot.agent.loop import _user_friendly_error

        # Rate limit
        msg = _user_friendly_error(RuntimeError("rate_limit: 429 too many requests"))
        assert "rate" in msg.lower() or "try again" in msg.lower()

        # Context overflow
        msg = _user_friendly_error(RuntimeError("context_length exceeded"))
        assert "long" in msg.lower() or "new" in msg.lower()

        # Auth error
        msg = _user_friendly_error(RuntimeError("auth: invalid api key denied"))
        assert "configuration" in msg.lower() or "admin" in msg.lower()

        # Unknown error
        msg = _user_friendly_error(RuntimeError("something unexpected"))
        assert "try again" in msg.lower() or "sorry" in msg.lower()

    async def test_provider_exception_propagates_from_process_message(self, tmp_path: Path):
        """_process_message propagates exceptions — the caller (run()) catches them."""

        class FailingProvider(LLMProvider):
            def get_default_model(self) -> str:
                return "test-model"

            async def chat(
                self,
                messages,
                tools=None,
                model=None,
                max_tokens=4096,
                temperature=0.7,
                metadata=None,
            ) -> LLMResponse:
                raise RuntimeError("rate_limit: 429 too many requests")

        loop = _make_loop(tmp_path, FailingProvider())
        with pytest.raises(RuntimeError, match="rate_limit"):
            await loop._process_message(_make_inbound("hello"))


# ---------------------------------------------------------------------------
# Workflow 4: Memory event storage and retrieval roundtrip
# ---------------------------------------------------------------------------


class TestWorkflowMemoryRoundtrip:
    """Events stored via MemoryStore must be retrievable in the same session."""

    def test_memory_store_roundtrip(self, tmp_path: Path):
        from nanobot.agent.memory import MemoryStore

        store = MemoryStore(tmp_path, embedding_provider="hash")

        # Store an event
        events = [
            {
                "id": "evt-workflow-1",
                "type": "preference",
                "summary": "User prefers vim keybindings.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            }
        ]
        store.append_events(events)

        # Retrieve it
        results = store.retrieve("vim keybindings", top_k=5)
        summaries = [r.get("summary", "").lower() for r in results]
        assert any("vim" in s for s in summaries)


# ---------------------------------------------------------------------------
# Workflow 5: Multi-turn conversation maintains session state
# ---------------------------------------------------------------------------


class TestWorkflowMultiTurn:
    """Second message in same session should have access to first message's context."""

    async def test_second_message_has_history(self, tmp_path: Path):
        provider = ScriptedProvider(
            [
                LLMResponse(content="Paris is the capital of France."),
                LLMResponse(content="Its population is about 2 million."),
            ]
        )
        loop = _make_loop(tmp_path, provider)

        # First message
        await loop._process_message(_make_inbound("What is the capital of France?"))
        # Second message in same session
        await loop._process_message(
            InboundMessage(
                channel="cli",
                chat_id="workflow-test",
                sender_id="user-1",
                content="What is the population?",
            )
        )

        # Second call should have more context than the first
        assert len(provider.call_log) == 2
        first_msg_count = len(provider.call_log[0]["messages"])
        second_msg_count = len(provider.call_log[1]["messages"])
        assert second_msg_count > first_msg_count, (
            "Second turn must include history from first turn"
        )
