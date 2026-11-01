import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.session_messages import SendSessionMessageTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import UserInputEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import UserInputAccepted
from nanobot.providers.base import LLMResponse
from nanobot.runtime_context import public_history_message
from nanobot.session.session_handles import SessionHandleResolver
from nanobot.session.session_messages import SESSION_MESSAGE_METADATA_KEY
from nanobot.session.webui_turns import WebuiTurnCoordinator
from nanobot.webui.history import record_from_fact


@pytest.fixture
async def loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "state")
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(max_tokens=4096)
    provider.chat_stream_with_retry = AsyncMock(
        return_value=LLMResponse(content="Reviewed", tool_calls=[], usage=None)
    )
    agent = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    try:
        yield agent
    finally:
        await agent.aclose()


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
    loop: AgentLoop,
) -> None:
    loop.sessions.save(loop.sessions.get_or_create("telegram:target"))
    msg = _message()

    response = await loop._process_message(msg)

    assert response is not None
    assert (response.channel, response.chat_id, response.content) == (
        "telegram",
        "target",
        "Reviewed",
    )
    provider_messages = loop.provider.chat_stream_with_retry.await_args.kwargs["messages"]
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
    loop: AgentLoop,
) -> None:
    loop.sessions.save(loop.sessions.get_or_create("telegram:target"))
    await loop._dispatch_inbound(_message("/stop"))
    await asyncio.wait_for(
        asyncio.gather(*loop._active_tasks["telegram:target"]), timeout=2,
    )
    response = await asyncio.wait_for(loop.bus.consume_outbound(), timeout=2)

    assert response.content == "Reviewed"
    loop.provider.chat_stream_with_retry.assert_awaited_once()


async def test_path_followup_reaches_running_turn(loop: AgentLoop) -> None:
    first_call = asyncio.Event()
    release = asyncio.Event()
    calls = []
    path = "/home/user/project"

    async def respond(**kwargs):
        calls.append(str(kwargs["messages"]))
        if len(calls) == 1:
            first_call.set()
            await release.wait()
        return LLMResponse(content="Reviewed")

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    run = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(InboundMessage(
            channel="weixin", sender_id="user", chat_id="path", content="Review the project",
        ))
        await asyncio.wait_for(first_call.wait(), 3)
        await loop.bus.publish_inbound(InboundMessage(
            channel="weixin", sender_id="user", chat_id="path", content=path,
        ))
        async with asyncio.timeout(3):
            while loop._pending_queues["weixin:path"].empty():
                await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(asyncio.gather(*loop._active_tasks["weixin:path"]), 5)

        assert len(calls) == 2
        assert path in calls[1]
        session = loop.sessions.get_or_create("weixin:path")
        visible = [public_history_message(row) for row in session.messages]
        assert any(row["content"] == path for row in visible)
        assert not any(row.get("_command") for row in session.messages)
    finally:
        release.set()
        loop.stop()
        await asyncio.wait_for(run, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("message_count", [1, 2], ids=["idle", "active"])
async def test_cross_session_input_preserves_source_in_live_events_and_history(
    loop: AgentLoop, message_count: int,
) -> None:
    source_key, target_key = "websocket:source", "websocket:target"
    await loop.sessions.state.get(source_key)
    await loop.sessions.state.get(target_key)
    await loop.sessions.state.mutate_metadata(target_key, lambda metadata: metadata.update(webui=True))
    handles = SessionHandleResolver(loop.sessions)
    source = await handles.ahandle_for_session(source_key)
    destination = await handles.ahandle_for_session(target_key)
    assert source is not None and destination is not None
    tool = SendSessionMessageTool(sessions=loop.sessions, bus=loop.bus)
    coordinator = WebuiTurnCoordinator(
        bus=loop.bus, sessions=loop.sessions,
        schedule_background=lambda coro: coro.close(),
    )
    disconnect = coordinator.subscribe()
    accepted = []
    disconnect_accepted = loop.bus.subscribe(accepted.append, UserInputAccepted)
    loop.bus.publish_outbound = AsyncMock()
    started, release = asyncio.Event(), asyncio.Event()

    async def respond(**kwargs):
        started.set()
        await release.wait()
        return LLMResponse(content="Reviewed", tool_calls=[], usage=None)

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    run = asyncio.create_task(loop.run())
    try:
        for index in range(message_count):
            with request_context(RequestContext(
                channel="websocket", chat_id="source", session_key=source_key,
            )):
                result = await tool.execute(
                    to=destination.name, content=f"Review {index}", expect_reply=False,
                )
            assert result == f"Sent to @{destination.name}."
            async with asyncio.timeout(3):
                while len(accepted) < index + 1:
                    await asyncio.sleep(0)
            await asyncio.wait_for(started.wait(), 3)
        release.set()
        await asyncio.wait_for(
            asyncio.gather(*loop._active_tasks[target_key]), 5,
        )
        assert len(accepted) == message_count
        events = [
            call.args[0].event for call in loop.bus.publish_outbound.await_args_list
            if isinstance(call.args[0].event, UserInputEvent)
        ]
        assert [event.content for event in events] == [f"Review {i}" for i in range(message_count)]
        provenance = {"id": source.id, "name": source.name}
        assert all(event.provenance["session_message"]["session"] == provenance for event in events)
        records = await loop.sessions.state.project_history(
            target_key,
            lambda history: [record_from_fact(fact, target_key) for fact in history.all_facts()],
        )
        inputs = [record for record in records if record.get("event") == "user"]
        assert [record["text"] for record in inputs] == [f"Review {i}" for i in range(message_count)]
        assert all(record["session_message"]["session"] == provenance for record in inputs)
        loop.provider.chat_stream_with_retry.assert_awaited()
    finally:
        release.set()
        disconnect()
        disconnect_accepted()
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
