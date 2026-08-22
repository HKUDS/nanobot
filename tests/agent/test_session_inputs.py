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
        return_value=LLMResponse(content="Reviewed", tool_calls=[], usage={})
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
        require_existing_session=True,
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
    loop.sessions.invalidate("telegram:target")
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
async def test_deleted_queued_session_message_does_not_recreate_target(
    tmp_path: Path,
) -> None:
    loop = _loop(tmp_path)
    target_key = "telegram:target"
    loop.sessions.save(loop.sessions.get_or_create(target_key))
    await loop.bus.publish_inbound(_message())

    assert loop.sessions.delete_session(target_key)

    run_task = asyncio.create_task(loop.run())
    try:
        async def wait_for_queue_to_drain() -> None:
            while not loop.bus.inbound.empty():
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_queue_to_drain(), timeout=2)
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=2)

    loop.provider.chat_with_retry.assert_not_awaited()
    assert loop.sessions.read_session_file(target_key) is None


@pytest.mark.asyncio
async def test_session_deleted_after_existence_check_does_not_recreate_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _loop(tmp_path)
    target_key = "telegram:target"
    loop.sessions.save(loop.sessions.get_or_create(target_key))
    loop.sessions.invalidate(target_key)

    original_read_metadata = loop.sessions.read_session_metadata

    def read_then_delete(key: str) -> dict[str, object] | None:
        metadata = original_read_metadata(key)
        assert metadata is not None
        assert loop.sessions.delete_session(key)
        return metadata

    read_metadata = MagicMock(side_effect=read_then_delete)
    monkeypatch.setattr(loop.sessions, "read_session_metadata", read_metadata)
    await loop.bus.publish_inbound(_message())

    run_task = asyncio.create_task(loop.run())
    try:
        response = await asyncio.wait_for(loop.bus.consume_outbound(), timeout=2)
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=2)

    read_metadata.assert_called_once_with(target_key)
    assert response.content == "Sorry, I encountered an error."
    loop.provider.chat_with_retry.assert_not_awaited()
    assert loop.sessions.read_session_file(target_key) is None


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
