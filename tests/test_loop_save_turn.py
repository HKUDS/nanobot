from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.bus.events import InboundMessage
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import Session


def _mk_loop() -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop._TOOL_RESULT_MAX_CHARS = AgentLoop._TOOL_RESULT_MAX_CHARS
    return loop


def _make_agent_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")


def test_save_turn_skips_multimodal_user_when_only_runtime_context() -> None:
    loop = _mk_loop()
    session = Session(key="test:runtime-only")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{"role": "user", "content": [{"type": "text", "text": runtime}]}],
        skip=0,
    )
    assert session.messages == []


def test_save_turn_keeps_image_placeholder_after_runtime_strip() -> None:
    loop = _mk_loop()
    session = Session(key="test:image")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image]"}]


def test_save_turn_keeps_tool_results_under_16k() -> None:
    loop = _mk_loop()
    session = Session(key="test:tool-result")
    content = "x" * 12_000

    loop._save_turn(
        session,
        [{"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": content}],
        skip=0,
    )

    assert session.messages[0]["content"] == content


def test_save_turn_preserves_assistant_usage_metadata() -> None:
    loop = _mk_loop()
    session = Session(key="test:assistant-usage")

    loop._save_turn(
        session,
        [{
            "role": "assistant",
            "content": "hello",
            "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
        }],
        skip=0,
    )

    assert session.messages[0]["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
    }


@pytest.mark.asyncio
async def test_process_message_persists_provider_usage_in_session(tmp_path: Path) -> None:
    loop = _make_agent_loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Hello!",
        tool_calls=[],
        usage={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
    ))
    loop.tools.get_definitions = MagicMock(return_value=[])

    msg = InboundMessage(channel="cli", sender_id="user1", chat_id="direct", content="Hi")
    result = await loop._process_message(msg)

    assert result is not None
    session = loop.sessions.get_or_create("cli:direct")
    assistant_messages = [m for m in session.messages if m.get("role") == "assistant"]
    assert assistant_messages
    assert assistant_messages[-1]["usage"] == {
        "prompt_tokens": 21,
        "completion_tokens": 9,
        "total_tokens": 30,
    }
