"""Tests for token-bounded session history replay."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import Session


def _make_loop(
    tmp_path: Path,
    context_window_tokens: int = 200_000,
    replay_reasoning: str | None = None,
) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=context_window_tokens,
        replay_reasoning=replay_reasoning,
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
async def test_process_message_replays_with_token_budget_only(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, context_window_tokens=32_768)
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[], usage=None)
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    with patch.object(session, "get_history", wraps=session.get_history) as get_history:
        result = await loop._process_message(
            InboundMessage(channel="cli", sender_id="user", chat_id="test", content="hello")
        )

    assert result is not None
    assert get_history.call_args.kwargs == {
        "max_tokens": loop._replay_token_budget(loop.llm_runtime()),
        "extend_to_user": False,
        "replay_reasoning": "recent",
    }


@pytest.mark.asyncio
async def test_token_budget_keeps_current_user_as_replay_boundary(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, context_window_tokens=8_000)
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[], usage=None)
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

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
    assert "long older turn" not in sent_text


def _reasoning_session() -> Session:
    session = Session(key="test:reasoning")
    session.add_message("user", "first question")
    session.add_message(
        "assistant",
        "first answer",
        reasoning_content="first thought",
        thinking_blocks=[{"type": "thinking", "thinking": "first thought", "signature": "sig-1"}],
    )
    session.add_message("user", "second question")
    session.add_message(
        "assistant",
        "second answer",
        reasoning_content="second thought",
        thinking_blocks=[{"type": "thinking", "thinking": "second thought", "signature": "sig-2"}],
    )
    return session


def test_replay_reasoning_all_is_the_default_replay_behavior() -> None:
    session = _reasoning_session()

    assert session.get_history() == session.get_history(replay_reasoning="all")
    assert session.get_history()[1]["reasoning_content"] == "first thought"


def test_replay_reasoning_recent_keeps_only_latest_turn_reasoning() -> None:
    history = _reasoning_session().get_history(replay_reasoning="recent")

    assert history[1] == {"role": "assistant", "content": "first answer"}
    assert history[3]["reasoning_content"] == "second thought"
    assert history[3]["thinking_blocks"][0]["signature"] == "sig-2"


def test_replay_reasoning_recent_keeps_unfinished_tool_loop() -> None:
    session = Session(key="test:tool-loop")
    session.add_message("user", "first question")
    session.add_message(
        "assistant",
        "first answer",
        reasoning_content="old reasoning",
        thinking_blocks=[{"type": "thinking", "thinking": "old reasoning", "signature": "sig-old"}],
    )
    session.add_message("user", "run it")
    session.messages.extend(_tool_round("call-1"))
    session.messages[-2]["thinking_blocks"] = [
        {"type": "thinking", "thinking": "current thought", "signature": "sig-current"}
    ]

    history = session.get_history(replay_reasoning="recent")

    assert history[1] == {"role": "assistant", "content": "first answer"}
    current_assistant = next(message for message in history if message.get("tool_calls"))
    assert current_assistant["thinking_blocks"][0]["signature"] == "sig-current"


def test_replay_reasoning_none_strips_all_reasoning() -> None:
    history = _reasoning_session().get_history(replay_reasoning="none")

    assert all("reasoning_content" not in message for message in history)
    assert all("thinking_blocks" not in message for message in history)


def test_replay_reasoning_recent_without_user_row_keeps_reasoning() -> None:
    session = Session(key="test:no-user")
    session.add_message(
        "assistant",
        "proactive note",
        reasoning_content="proactive reasoning",
        thinking_blocks=[{"type": "thinking", "thinking": "proactive reasoning", "signature": "sig"}],
    )

    history = session.get_history(replay_reasoning="recent")

    assert history[0]["reasoning_content"] == "proactive reasoning"


def test_replay_reasoning_leaves_persisted_record_intact() -> None:
    session = _reasoning_session()

    session.get_history(replay_reasoning="recent")

    assert session.messages[1]["reasoning_content"] == "first thought"
    assert session.messages[3]["thinking_blocks"][0]["signature"] == "sig-2"


def test_replay_reasoning_config_default_and_alias() -> None:
    assert AgentDefaults().replay_reasoning == "recent"
    assert AgentDefaults.model_validate({"replayReasoning": "all"}).replay_reasoning == "all"
    assert AgentDefaults.model_validate({"replay_reasoning": "none"}).replay_reasoning == "none"


@pytest.mark.asyncio
async def test_replay_reasoning_setting_reaches_history_replay(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, context_window_tokens=32_768, replay_reasoning="all")
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[], usage=None)
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    with patch.object(session, "get_history", wraps=session.get_history) as get_history:
        result = await loop._process_message(
            InboundMessage(channel="cli", sender_id="user", chat_id="test", content="hello")
        )

    assert result is not None
    assert get_history.call_args.kwargs["replay_reasoning"] == "all"
