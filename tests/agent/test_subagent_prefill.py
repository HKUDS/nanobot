"""End-to-end simulation of the subagent → announce → main-agent flow.

Reproduces the bug where a subagent completion triggers an assistant-prefill
error on Claude:

    Error code: 400 - 'This model does not support assistant message prefill.
    The conversation must end with a user message.'

The test spins up a real AgentLoop with a fake Anthropic-like provider,
simulates the full subagent lifecycle, and asserts that:
  1. The messages sent to the LLM never end with an assistant message.
  2. The user receives a friendly summary, not a raw API error.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


# ---------------------------------------------------------------------------
# A provider that rejects assistant-prefill (like Claude with thinking)
# ---------------------------------------------------------------------------

class PrefillRejectingProvider(LLMProvider):
    """Mimics Claude's behaviour: rejects messages ending with role=assistant."""

    def __init__(self):
        super().__init__()
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(self, messages, **kwargs) -> LLMResponse:
        self.calls.append(list(messages))

        # Check for the prefill condition the real API enforces
        non_system = [m for m in messages if m.get("role") != "system"]
        if non_system and non_system[-1].get("role") == "assistant":
            raise Exception(
                "Error code: 400 - {'type': 'error', 'error': {'type': "
                "'invalid_request_error', 'message': 'This model does not "
                "support assistant message prefill. The conversation must "
                "end with a user message.'}}"
            )

        return LLMResponse(content="Here is a summary for the user.", usage={})

    def get_default_model(self) -> str:
        return "claude-test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_loop_with_provider(tmp_path: Path, provider: LLMProvider):
    """Build a real AgentLoop wired to the given provider."""
    from nanobot.agent.loop import AgentLoop

    bus = MessageBus()

    # Create minimal workspace files so ContextBuilder doesn't crash
    (tmp_path / "SOUL.md").write_text("You are a test agent.")
    (tmp_path / "AGENTS.md").write_text("## Instructions\nBe helpful.")
    (tmp_path / "memory").mkdir(exist_ok=True)

    with patch("nanobot.agent.loop.SubagentManager") as MockSub:
        MockSub.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            max_iterations=2,
        )

    return loop, bus


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subagent_announce_does_not_cause_prefill_error(tmp_path):
    """Simulate: subagent completes → announces result → main agent processes.

    With the old code (current_role="assistant"), the PrefillRejectingProvider
    would raise and the user would see a raw API error.  After the fix, the
    messages end with a user message and the LLM responds normally.
    """
    provider = PrefillRejectingProvider()
    loop, bus = _make_loop_with_provider(tmp_path, provider)

    # This is exactly what SubagentManager._announce_result publishes
    subagent_msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="telegram:123",
        content=(
            "[Subagent 'generate invite' completed successfully]\n\n"
            "Task: Generate an invitation image for tola_bday\n\n"
            "Result:\n"
            '{"status": "ok", "image_path": "/workspace/files/tola_bday_invite.png"}\n\n'
            "Summarize this naturally for the user."
        ),
    )

    response = await loop._process_message(subagent_msg)

    # The LLM should have been called successfully
    assert provider.calls, "Provider was never called"

    # Every call's non-system messages must end with a user message
    for i, call_messages in enumerate(provider.calls):
        non_system = [m for m in call_messages if m.get("role") != "system"]
        assert non_system, f"Call {i}: no non-system messages"
        assert non_system[-1]["role"] == "user", (
            f"Call {i}: last non-system message has role='{non_system[-1]['role']}', "
            f"expected 'user'. This would trigger assistant-prefill rejection."
        )

    # User should get a real response, not a raw error
    assert response is not None
    assert "summary" in response.content.lower() or "error" not in response.content.lower()
    assert "invalid_request_error" not in response.content


@pytest.mark.asyncio
async def test_subagent_announce_old_behaviour_would_fail(tmp_path):
    """Prove the bug existed: if we force current_role='assistant',
    the PrefillRejectingProvider rejects the call and the raw error leaks."""
    provider = PrefillRejectingProvider()
    loop, bus = _make_loop_with_provider(tmp_path, provider)

    # Monkey-patch build_messages to force the old broken behaviour
    original_build = loop.context.build_messages

    def broken_build(**kwargs):
        kwargs["current_role"] = "assistant"
        return original_build(**kwargs)

    loop.context.build_messages = broken_build

    subagent_msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="telegram:123",
        content="[Subagent 'test' completed]\nResult: done",
    )

    response = await loop._process_message(subagent_msg)

    # With the old behaviour the LLM rejects the prefill.
    # The runner's error_message should be returned instead of the raw error.
    assert response is not None
    assert response.content == "Sorry, I encountered an error calling the AI model."
    assert "invalid_request_error" not in response.content


@pytest.mark.asyncio
async def test_full_spawn_to_announce_flow_no_prefill(tmp_path):
    """Simulate the complete lifecycle: user asks → Homer spawns subagent →
    subagent completes → result announced → main agent summarizes.

    Verifies no assistant-prefill at any step."""
    provider = PrefillRejectingProvider()
    loop, bus = _make_loop_with_provider(tmp_path, provider)

    # Step 1: User sends "generate an invite" (normal user message)
    # The LLM would respond with a spawn tool call, but we skip that
    # and go straight to what happens after the subagent completes.

    # Step 2: Simulate the user's original message being in session history
    session = loop.sessions.get_or_create("telegram:123")
    session.messages.append({
        "role": "user",
        "content": "Generate an invite for Tola's birthday party",
    })
    session.messages.append({
        "role": "assistant",
        "content": 'I\'ll generate that invite for you now. Starting the image generation...',
        "tool_calls": [{"id": "call_1", "function": {"name": "spawn", "arguments": "{}"}}],
    })
    session.messages.append({
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "spawn",
        "content": "Subagent [generate invite] started (id: abc123)",
    })
    session.messages.append({
        "role": "assistant",
        "content": "I've started generating the invite. I'll let you know when it's ready!",
    })
    loop.sessions.save(session)

    # Step 3: Subagent announces completion (this is the critical path)
    announce_msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="telegram:123",
        content=(
            "[Subagent 'generate invite' completed successfully]\n\n"
            "Task: Generate invitation image\n\n"
            "Result:\n"
            "Image saved to /workspace/files/tola_bday_invite.png\n\n"
            "Summarize this naturally for the user."
        ),
    )

    response = await loop._process_message(announce_msg)

    # Verify every LLM call had messages ending with user role
    for i, call_messages in enumerate(provider.calls):
        non_system = [m for m in call_messages if m.get("role") != "system"]
        assert non_system[-1]["role"] == "user", (
            f"Call {i}: last message role='{non_system[-1]['role']}' — "
            f"would trigger prefill error with Claude"
        )

    # User gets a proper response
    assert response is not None
    assert "invalid_request_error" not in response.content

    # Verify the injected subagent announcement is NOT in session history
    session = loop.sessions.get_or_create("telegram:123")
    user_messages = [m for m in session.messages if m.get("role") == "user"]
    for um in user_messages:
        content = um.get("content", "")
        assert "[Subagent" not in content, (
            f"Subagent announcement leaked into session history: {content[:80]}"
        )

    # But the assistant's summary IS saved
    assistant_messages = [m for m in session.messages if m.get("role") == "assistant"]
    last_assistant = assistant_messages[-1] if assistant_messages else None
    assert last_assistant is not None, "Assistant response was not saved to session"
    assert last_assistant.get("content"), "Assistant response is empty"


@pytest.mark.asyncio
async def test_subagent_result_is_ephemeral_not_persisted(tmp_path):
    """The subagent announcement should be used for one LLM call then discarded.
    Only the assistant's response should be saved to session history."""
    provider = PrefillRejectingProvider()
    loop, bus = _make_loop_with_provider(tmp_path, provider)

    announce_msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="telegram:123",
        content="[Subagent 'research' completed]\nResult: found 3 relevant docs",
    )

    await loop._process_message(announce_msg)

    session = loop.sessions.get_or_create("telegram:123")

    # The injected announcement must NOT appear in session messages
    for m in session.messages:
        content = m.get("content", "")
        assert "[Subagent" not in content, (
            f"Subagent announcement persisted to session (role={m.get('role')}): "
            f"{content[:80]}"
        )

    # The assistant's response SHOULD be persisted
    assert any(m.get("role") == "assistant" for m in session.messages), (
        "No assistant response saved — the LLM's summary was lost"
    )
