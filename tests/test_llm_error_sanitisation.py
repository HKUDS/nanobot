"""Tests for sanitising LLM-error responses before they reach end users.

Triggered by 2026-05-30 11:35: Ruth received the raw
`litellm.BadRequestError: AnthropicException - {"type":"error", ...
"Your credit balance is too low..."}` text via email because the agent loop
treated the LLM exception string as the assistant's final content."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch


def _make_loop():
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        return AgentLoop(bus=bus, provider=provider, workspace=workspace, max_iterations=2)


@dataclass
class _Resp:
    """Just enough of LLMResponse to drive _run_agent_loop."""
    content: str = ""
    tool_calls: list = None  # type: ignore[assignment]
    finish_reason: str = "stop"
    reasoning_content: str | None = None
    thinking_blocks: list | None = None
    usage: dict = None  # type: ignore[assignment]

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


import pytest


@pytest.mark.asyncio
async def test_llm_error_does_not_leak_provider_text_to_user() -> None:
    """The exact failure mode: LLM call surfaces an Anthropic billing error,
    and the agent loop must NOT forward it verbatim."""
    loop = _make_loop()
    leaked_text = (
        "Error calling LLM: litellm.BadRequestError: AnthropicException - "
        '{"type":"error","error":{"type":"invalid_request_error",'
        '"message":"Your credit balance is too low to access the Anthropic API. '
        'Please go to Plans & Billing to upgrade or purchase credits."}}'
    )
    loop.provider.chat = AsyncMock(return_value=_Resp(
        content=leaked_text,
        finish_reason="error",
        usage={"total_tokens": 10},
    ))
    # Stub context builder methods used inside the loop.
    loop.context.add_assistant_message = MagicMock(side_effect=lambda msgs, *a, **kw: msgs)
    loop.context.add_tool_result = MagicMock(side_effect=lambda msgs, *a, **kw: msgs)

    final, tools_used, _msgs = await loop._run_agent_loop([{"role": "user", "content": "hi"}])

    assert "credit balance" not in (final or ""), "billing details must not leak"
    assert "BadRequestError" not in (final or ""), "exception class name must not leak"
    assert "litellm" not in (final or "").lower(), "internal library name must not leak"
    assert "AnthropicException" not in (final or ""), "provider exception class must not leak"
    assert "try again" in (final or "").lower(), "user gets a generic, actionable message"


@pytest.mark.asyncio
async def test_llm_error_with_empty_content_still_returns_generic_message() -> None:
    loop = _make_loop()
    loop.provider.chat = AsyncMock(return_value=_Resp(
        content="",
        finish_reason="error",
        usage={"total_tokens": 5},
    ))
    loop.context.add_assistant_message = MagicMock(side_effect=lambda msgs, *a, **kw: msgs)
    loop.context.add_tool_result = MagicMock(side_effect=lambda msgs, *a, **kw: msgs)

    final, _tools, _msgs = await loop._run_agent_loop([{"role": "user", "content": "hi"}])
    assert "Sorry" in (final or "")
    assert "try again" in (final or "").lower()
