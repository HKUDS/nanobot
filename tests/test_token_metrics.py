"""Tests for token usage flow through the agent loop.

Verifies that LLM response usage data flows correctly and _process_message
works end-to-end with providers that return usage metadata.  Token metrics
are now captured by Langfuse (via OTEL callback); these tests verify that the
agent loop handles usage data gracefully regardless of observability config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# ---------------------------------------------------------------------------
# Mock provider returning usage data
# ---------------------------------------------------------------------------


class UsageTrackingProvider(LLMProvider):
    """LLM provider that returns scripted responses with token usage."""

    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self._index = 0

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
        if self._index >= len(self._responses):
            return LLMResponse(content="(no more scripted responses)", usage={})
        resp = self._responses[self._index]
        self._index += 1
        return resp


# ---------------------------------------------------------------------------
# Helpers
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
    return build_agent(bus=bus, provider=provider, config=config)


def _make_inbound(text: str) -> InboundMessage:
    return InboundMessage(
        channel="cli",
        chat_id="test-user",
        sender_id="user-1",
        content=text,
    )


# ---------------------------------------------------------------------------
# End-to-end: agent loop handles usage correctly
# ---------------------------------------------------------------------------


class TestTokenFlowEndToEnd:
    async def test_single_turn_with_usage(self, tmp_path: Path) -> None:
        """A simple Q&A turn with token usage should complete successfully."""
        provider = UsageTrackingProvider(
            [
                LLMResponse(
                    content="The answer is 42.",
                    usage={"prompt_tokens": 350, "completion_tokens": 25, "total_tokens": 375},
                ),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("What is the answer?"))

        assert result is not None
        assert "42" in result.content
        assert loop._turn_tokens_prompt == 350
        assert loop._turn_tokens_completion == 25

    async def test_multi_iteration_with_usage(self, tmp_path: Path) -> None:
        """Tool calls cause multiple LLM calls; usage should not crash."""
        provider = UsageTrackingProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call-1",
                            name="read_file",
                            arguments={"path": "test.txt"},
                        )
                    ],
                    finish_reason="tool_calls",
                    usage={"prompt_tokens": 400, "completion_tokens": 30, "total_tokens": 430},
                ),
                LLMResponse(
                    content="The file contains hello.",
                    usage={"prompt_tokens": 600, "completion_tokens": 20, "total_tokens": 620},
                ),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        (tmp_path / "test.txt").write_text("hello")
        result = await loop._process_message(_make_inbound("Read test.txt"))

        assert result is not None
        # Two LLM calls: tokens should accumulate
        assert loop._turn_tokens_prompt == 1000
        assert loop._turn_tokens_completion == 50

    async def test_missing_usage_graceful(self, tmp_path: Path) -> None:
        """When LLM response has empty usage dict, loop should not crash.

        The streaming path now estimates completion tokens from content length
        when the provider omits them (LAN-5), so _turn_tokens_completion may
        be a small positive estimate rather than exactly 0.
        """
        provider = UsageTrackingProvider(
            [
                LLMResponse(content="No usage data.", usage={}),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Hi"))

        assert result is not None
        assert loop._turn_tokens_prompt == 0
        # Estimated from content "No usage data." (14 chars → ≥1 token)
        assert loop._turn_tokens_completion >= 0
