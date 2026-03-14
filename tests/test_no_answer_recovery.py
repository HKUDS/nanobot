"""Tests for the no-answer recovery mechanism.

Covers:
- Recovery retry succeeds when main loop returns None
- Recovery falls through to explanation when recovery also fails
- content_filter finish_reason is detected and retried
- length finish_reason with empty content is retried
- _strip_think warns when stripping non-empty content to None
- _build_no_answer_explanation returns correct help_line for questions vs statements
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.base import LLMProvider, LLMResponse

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_agent_loop.py)
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
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.call_log.append(
            {
                "messages_count": len(messages),
                "has_tools": tools is not None,
                "model": model,
            }
        )
        if self._index >= len(self._responses):
            return LLMResponse(content="(no more scripted responses)")
        resp = self._responses[self._index]
        self._index += 1
        return resp


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
        chat_id="test-user",
        sender_id="user-1",
        content=text,
    )


# ---------------------------------------------------------------------------
# Recovery retry tests
# ---------------------------------------------------------------------------


class TestRecoveryRetry:
    """Test that recovery LLM call is attempted when main loop produces None."""

    @pytest.mark.asyncio
    async def test_recovery_succeeds(self, tmp_path: Path):
        """When main loop returns None but recovery call succeeds, user gets an answer."""
        provider = ScriptedProvider(
            [
                # Main loop: LLM returns empty content -> final_content = None
                LLMResponse(content=None),
                # Recovery call: LLM answers directly
                LLMResponse(content="I have 3 cron jobs configured."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("How many cron jobs you have?"))

        assert result is not None
        assert "cron" in result.content.lower()
        # Recovery call should have tools=None (no tool definitions)
        assert len(provider.call_log) >= 2
        recovery_call = provider.call_log[-1]
        assert recovery_call["has_tools"] is False

    @pytest.mark.asyncio
    async def test_recovery_fails_falls_through(self, tmp_path: Path):
        """When both main loop and recovery return None, user gets the fallback explanation."""
        provider = ScriptedProvider(
            [
                # Main loop: empty
                LLMResponse(content=None),
                # Recovery: also empty
                LLMResponse(content=None),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("What is the meaning of life?"))

        assert result is not None
        assert "Sorry" in result.content
        assert "try rephrasing" in result.content.lower()

    @pytest.mark.asyncio
    async def test_recovery_with_think_only_response(self, tmp_path: Path):
        """Recovery handles <think>-only responses gracefully."""
        provider = ScriptedProvider(
            [
                # Main loop: think-only (stripped to None)
                LLMResponse(content="<think>Let me reason about this...</think>"),
                # Recovery: also think-only
                LLMResponse(content="<think>Still just thinking.</think>"),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Why is the sky blue?"))

        assert result is not None
        # Both None -> falls back to explanation
        assert "Sorry" in result.content

    @pytest.mark.asyncio
    async def test_recovery_error_falls_through(self, tmp_path: Path):
        """When recovery LLM call returns an error, falls through to explanation."""
        provider = ScriptedProvider(
            [
                # Main loop: empty
                LLMResponse(content=None),
                # Recovery: error
                LLMResponse(content="Error calling LLM: timeout", finish_reason="error"),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Hello?"))

        assert result is not None
        assert "Sorry" in result.content


# ---------------------------------------------------------------------------
# content_filter / length finish_reason tests
# ---------------------------------------------------------------------------


class TestContentFilterHandling:
    """Test that content_filter finish_reason is detected and retried."""

    @pytest.mark.asyncio
    async def test_content_filter_retry_then_success(self, tmp_path: Path):
        """First attempt is filtered, second attempt succeeds."""
        provider = ScriptedProvider(
            [
                LLMResponse(content=None, finish_reason="content_filter"),
                LLMResponse(content="Here's a safe response."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Tell me a joke"))

        assert result is not None
        assert "safe response" in result.content

    @pytest.mark.asyncio
    async def test_content_filter_persistent(self, tmp_path: Path):
        """Two consecutive content_filter responses -> specific error message."""
        provider = ScriptedProvider(
            [
                LLMResponse(content=None, finish_reason="content_filter"),
                LLMResponse(content=None, finish_reason="content_filter"),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Tell me something edgy"))

        assert result is not None
        assert "content filter" in result.content.lower()

    @pytest.mark.asyncio
    async def test_length_empty_content_retry(self, tmp_path: Path):
        """finish_reason=length with no content is retried."""
        provider = ScriptedProvider(
            [
                LLMResponse(content=None, finish_reason="length"),
                LLMResponse(content="Short answer."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Explain quantum physics"))

        assert result is not None
        assert "Short answer" in result.content

    @pytest.mark.asyncio
    async def test_length_with_partial_content_accepted(self, tmp_path: Path):
        """finish_reason=length with non-empty content is accepted (partial answer)."""
        provider = ScriptedProvider(
            [
                LLMResponse(content="Quantum physics is the study of...", finish_reason="length"),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Explain quantum physics"))

        assert result is not None
        assert "Quantum physics" in result.content


# ---------------------------------------------------------------------------
# _strip_think logging tests
# ---------------------------------------------------------------------------


class TestStripThink:
    """Test _strip_think behavior."""

    def test_think_only_returns_none(self):
        """Stripping a <think>-only response returns None."""
        assert AgentLoop._strip_think("<think>Some reasoning here</think>") is None

    def test_normal_content_preserved(self):
        """Normal content is returned unchanged."""
        assert AgentLoop._strip_think("Hello world") == "Hello world"

    def test_none_input_returns_none(self):
        """None input returns None."""
        assert AgentLoop._strip_think(None) is None

    def test_mixed_think_and_text(self):
        """Content with <think> tags and text preserves only the text."""
        result = AgentLoop._strip_think("<think>reasoning</think>The answer is 42.")
        assert result == "The answer is 42."


# ---------------------------------------------------------------------------
# _build_no_answer_explanation tests
# ---------------------------------------------------------------------------


class TestBuildNoAnswerExplanation:
    """Test improved fallback message generation."""

    def test_question_gets_rephrase_help(self):
        """A question should suggest rephrasing, not sharing a fact."""
        result = AgentLoop._build_no_answer_explanation("How many cron jobs?", [])
        assert "rephras" in result.lower()
        assert "share the fact" not in result.lower()

    def test_question_mark_detected(self):
        """Any text with ? should be treated as a question."""
        result = AgentLoop._build_no_answer_explanation("cron jobs?", [])
        assert "rephras" in result.lower()

    def test_statement_gets_share_fact_help(self):
        """A statement should suggest sharing a fact."""
        result = AgentLoop._build_no_answer_explanation("My birthday is in March", [])
        assert "share the fact" in result.lower()

    def test_no_tools_reason_improved(self):
        """When no tool results exist, the reason should not mention tools."""
        result = AgentLoop._build_no_answer_explanation("What is 2+2?", [])
        assert "did not produce a response" in result.lower()
        assert "tools or memory" not in result.lower()

    def test_tool_failure_reason(self):
        """When tool results include 'not found', the reason mentions it."""
        msgs = [{"role": "tool", "name": "read_file", "content": "Error: not found"}]
        result = AgentLoop._build_no_answer_explanation("What is in test.txt?", msgs)
        assert "read_file" in result

    def test_empty_user_text(self):
        """Empty user text should still produce a valid fallback."""
        result = AgentLoop._build_no_answer_explanation("", [])
        assert "Sorry" in result
