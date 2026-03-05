"""Tests for the ephemeral history-boundary wrapper in AgentLoop._process_message.

Verifies that:
  - The LLM receives the "END OF HISTORY" wrapped version of the user message.
  - The wrapper is NOT persisted into session history; only the original content is saved.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


_WRAPPER_MARKER = "--- END OF HISTORY ---"


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model", memory_window=10)


class TestEphemeralHistoryWrapper:
    """Wrapper must be visible to the LLM but absent from persisted session history."""

    @pytest.mark.asyncio
    async def test_llm_receives_wrapped_content(self, tmp_path: Path) -> None:
        """The provider.chat call must contain the boundary wrapper in the last user message."""
        loop = _make_loop(tmp_path)
        loop.provider.chat = AsyncMock(
            return_value=LLMResponse(content="pong", tool_calls=[])
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="ping")
        await loop._process_message(msg)

        call_kwargs = loop.provider.chat.call_args
        assert call_kwargs is not None
        messages_sent = call_kwargs.kwargs.get("messages") or call_kwargs.args[0]

        # Find the last user message (current request)
        user_msgs = [m for m in messages_sent if m.get("role") == "user"]
        last_user = user_msgs[-1]
        content = last_user.get("content", "")
        if isinstance(content, list):
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            content = " ".join(text_parts)

        assert _WRAPPER_MARKER in content, (
            "LLM should receive the ephemeral 'END OF HISTORY' boundary wrapper."
        )
        assert "ping" in content

    @pytest.mark.asyncio
    async def test_wrapper_not_persisted_in_session_history(self, tmp_path: Path) -> None:
        """Session history must store the plain original message, never the wrapper text."""
        loop = _make_loop(tmp_path)
        loop.provider.chat = AsyncMock(
            return_value=LLMResponse(content="pong", tool_calls=[])
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="ping")
        await loop._process_message(msg)

        session = loop.sessions.get("cli:direct")
        assert session is not None

        for entry in session.messages:
            content = entry.get("content", "")
            if isinstance(content, str):
                assert _WRAPPER_MARKER not in content, (
                    f"Ephemeral wrapper must not be persisted in session history. "
                    f"Found in: {content[:120]}"
                )
            elif isinstance(content, list):
                for part in content:
                    text = part.get("text", "") if isinstance(part, dict) else ""
                    assert _WRAPPER_MARKER not in text, (
                        "Ephemeral wrapper must not be persisted in session history."
                    )

    @pytest.mark.asyncio
    async def test_original_content_is_persisted(self, tmp_path: Path) -> None:
        """The original user message content must appear in session history."""
        loop = _make_loop(tmp_path)
        loop.provider.chat = AsyncMock(
            return_value=LLMResponse(content="pong", tool_calls=[])
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="ping")
        await loop._process_message(msg)

        session = loop.sessions.get("cli:direct")
        assert session is not None

        user_entries = [e for e in session.messages if e.get("role") == "user"]
        plain_texts = []
        for e in user_entries:
            c = e.get("content", "")
            if isinstance(c, str):
                plain_texts.append(c)
            elif isinstance(c, list):
                plain_texts.extend(p.get("text", "") for p in c if isinstance(p, dict))

        assert any("ping" in t and _WRAPPER_MARKER not in t for t in plain_texts), (
            "Original 'ping' content should be persisted in session history without the wrapper."
        )
