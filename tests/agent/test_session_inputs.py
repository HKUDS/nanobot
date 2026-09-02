import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.runtime_context import public_history_message
from nanobot.session.session_messages import SESSION_MESSAGE_METADATA_KEY


def _loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(max_tokens=4096)
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="Reviewed", tool_calls=[], usage=None)
    )
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )


def _message(content: str = "Please review") -> InboundMessage:
    envelope = {
        "message_id": "message-1",
        "created_at_ms": 1,
        "expect_reply": True,
        "source_handle": "luma",
        "source_session_key": "websocket:source",
        "target_session_key": "telegram:target",
    }
    return InboundMessage(
        channel="system",
        sender_id="session",
        chat_id="telegram:target",
        content=content,
        metadata={SESSION_MESSAGE_METADATA_KEY: envelope},
        session_key_override="telegram:target",
        input_role="user",
    )


@pytest.mark.asyncio
async def test_session_message_runs_as_user_input_and_replies_on_target_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "state")
    loop = _loop(tmp_path)
    loop.sessions.save(loop.sessions.get_or_create("telegram:target"))
    msg = _message()

    response = await loop._process_message(msg)

    assert response is not None
    assert (response.channel, response.chat_id, response.content) == (
        "telegram",
        "target",
        "Reviewed",
    )
    provider_messages = loop.provider.chat_with_retry.await_args.kwargs["messages"]
    provider_input = next(
        row for row in reversed(provider_messages) if row.get("role") == "user"
    )
    assert provider_input["content"].startswith("Please review")
    assert "Message from @luma." in provider_input["content"]
    assert "Reply with send_session_message." in provider_input["content"]

    stored = loop.sessions.get_or_create("telegram:target").messages
    user_row = next(row for row in stored if row.get("role") == "user")
    assert public_history_message(user_row)["content"] == "Please review"
    assert SESSION_MESSAGE_METADATA_KEY not in user_row


@pytest.mark.asyncio
async def test_session_message_text_is_not_dispatched_as_a_slash_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "state")
    loop = _loop(tmp_path)
    loop.sessions.save(loop.sessions.get_or_create("telegram:target"))
    task = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(_message("/stop"))
        response = await asyncio.wait_for(loop.bus.consume_outbound(), timeout=2)

        assert response.content == "Reviewed"
        loop.provider.chat_with_retry.assert_awaited_once()
    finally:
        loop.stop()
        await asyncio.wait_for(task, timeout=2)
