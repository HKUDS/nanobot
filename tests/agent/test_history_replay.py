"""Tests for token-bounded session history replay."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import Session
from nanobot.session.summary import SUMMARY_CONTINUATION_TEXT


def _make_loop(tmp_path: Path, context_window_tokens: int = 200_000) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=context_window_tokens,
    )


def _populated_session(turns: int) -> Session:
    session = Session(key="test:populated")
    for index in range(turns):
        session.add_message("user", f"msg-{index}")
        session.add_message("assistant", f"reply-{index}")
    return session


def _tool_round(call_id: str) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "name": "x", "content": "ok"},
    ]


def test_default_history_has_no_message_count_limit() -> None:
    session = _populated_session(1_001)

    history = session.get_history()

    assert len(history) == 2_002
    assert history[0]["content"] == "msg-0"
    assert history[-1]["content"] == "reply-1000"


def test_explicit_message_limit_still_starts_at_user_turn() -> None:
    history = _populated_session(30).get_history(max_messages=25)

    assert len(history) <= 25
    assert history[0]["role"] == "user"


@pytest.mark.asyncio
async def test_process_message_hands_complete_replay_to_runner(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, context_window_tokens=32_768)
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[], usage=None)
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    session = loop.sessions.get_or_create("cli:test")
    with patch.object(session, "get_history", wraps=session.get_history) as get_history:
        result = await loop._process_message(
            InboundMessage(channel="cli", sender_id="user", chat_id="test", content="hello")
        )

    assert result is not None
    assert get_history.call_args.kwargs == {"extend_to_user": False}


@pytest.mark.asyncio
async def test_runner_checkpoint_keeps_current_user_as_replay_boundary(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, context_window_tokens=8_000)
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[], usage=None)
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    session = loop.sessions.get_or_create("cli:test")
    session.add_message("user", "old")
    session.add_message("assistant", "old answer")
    session.add_message("user", "long older turn")
    for index in range(70):
        session.messages.extend(_tool_round(f"older-{index}"))
    session.add_message("assistant", "older final")

    result = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="test",
            content="new question",
        )
    )

    assert result is not None
    sent_messages = loop.provider.chat_with_retry.await_args.kwargs["messages"]
    sent_text = "\n".join(str(message.get("content")) for message in sent_messages)
    assert "new question" in sent_text
    assert [message["role"] for message in sent_messages] == ["system", "user", "user"]
    assert sent_messages[1]["content"] == SUMMARY_CONTINUATION_TEXT
    assert any(message.get("content") == "long older turn" for message in session.messages)
