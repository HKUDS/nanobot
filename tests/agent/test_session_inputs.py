"""Session-authored user input behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META, public_history_message
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.session_handles import SessionHandleDirectory
from nanobot.session.session_messages import (
    SESSION_MESSAGE_METADATA_KEY,
    SESSION_REPLY_TIMEOUT_METADATA_KEY,
)
from nanobot.session.webui_turns import (
    project_session_message_input,
    websocket_turn_wall_started_at,
)
from nanobot.webui.transcript import read_transcript_lines


@pytest.fixture(autouse=True)
def _isolate_webui_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nanobot.webui.transcript.get_webui_dir",
        lambda: tmp_path / "webui",
    )


def _loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(max_tokens=4096)
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="Reviewed", tool_calls=[], usage={})
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    for key in ("websocket:source", "websocket:target"):
        session = loop.sessions.get_or_create(key)
        session.metadata["webui"] = True
        loop.sessions.save(session)
    return loop


def _session_message(
    loop: AgentLoop,
    content: str = "Review the change",
    *,
    message_id: str = "handle-message-1",
    expect_reply: bool = True,
    source_key: str = "websocket:source",
    target_key: str = "websocket:target",
) -> InboundMessage:
    directory = SessionHandleDirectory(loop.sessions)
    handles = directory.ensure_many([source_key, target_key])
    source = handles[source_key]
    target = handles[target_key]
    is_webui = target_key.startswith("websocket:")
    return InboundMessage(
        channel="websocket" if is_webui else "system",
        sender_id="session",
        chat_id=target_key.split(":", 1)[1] if is_webui else target_key,
        content=content,
        metadata={
            SESSION_MESSAGE_METADATA_KEY: {
                "message_id": message_id,
                "created_at_ms": 1,
                "expect_reply": expect_reply,
                "source": {
                    "name": source.name,
                    "session_key": source.session_key,
                    "handle_id": source.id,
                    "color_slot": source.color_slot,
                },
                "target": {
                    "name": target.name,
                    "session_key": target.session_key,
                },
            }
        },
        session_key_override=target_key,
        require_existing_session=True,
    )


def _session_reply_timeout_message(loop: AgentLoop, *, timeout_seconds: int = 60) -> InboundMessage:
    directory = SessionHandleDirectory(loop.sessions)
    handles = directory.ensure_many(["websocket:source", "websocket:target"])
    waiter = handles["websocket:source"]
    handle = handles["websocket:target"]
    return InboundMessage(
        channel="system",
        sender_id="session_timeout",
        chat_id="websocket:source",
        content="",
        metadata={
            SESSION_REPLY_TIMEOUT_METADATA_KEY: {
                "message_id": "handle-message-1",
                "created_at_ms": 1,
                "expect_reply": True,
                "timeout_seconds": timeout_seconds,
                "source": {
                    "name": waiter.name,
                    "session_key": waiter.session_key,
                    "handle_id": waiter.id,
                    "color_slot": waiter.color_slot,
                },
                "target": {
                    "name": handle.name,
                    "session_key": handle.session_key,
                },
            },
        },
        session_key_override="websocket:source",
        require_existing_session=True,
    )

@pytest.mark.asyncio
async def test_session_input_keeps_reply_guidance_private_runtime_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    loop = _loop(tmp_path)
    loop.sessions.invalidate("websocket:target")

    response = await loop._process_message(_session_message(loop))

    assert response is not None
    assert (response.channel, response.chat_id) == ("websocket", "target")
    directory = SessionHandleDirectory(loop.sessions)
    handles = directory.ensure_many(["websocket:source", "websocket:target"])
    source_name = handles["websocket:source"].name
    target_name = handles["websocket:target"].name
    expected_provider_input = (
        "Review the change\n\n"
        f"Your handle: @{target_name}.\n\n"
        f"Message from @{source_name}. Reply with send_session_message."
    )
    session = loop.sessions.get_or_create("websocket:target")
    session_input = next(message for message in session.messages if message.get("role") == "user")
    assert session_input["content"] == expected_provider_input
    assert public_history_message(session_input)["content"] == "Review the change"
    assert SESSION_MESSAGE_METADATA_KEY in session_input

    provider_messages = loop.provider.chat_with_retry.await_args.kwargs["messages"]
    provider_input = next(
        message for message in reversed(provider_messages) if message.get("role") == "user"
    )
    assert provider_input["content"] == expected_provider_input

    loop.sessions.invalidate("websocket:target")
    replay = loop.sessions.get_or_create("websocket:target").get_history()
    replay_input = next(message for message in replay if message.get("role") == "user")
    assert replay_input["content"] == provider_input["content"]


@pytest.mark.asyncio
async def test_session_input_runs_as_user_turn_for_non_websocket_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    loop = _loop(tmp_path)
    target_key = "telegram:target"
    loop.sessions.save(loop.sessions.get_or_create(target_key))
    loop.sessions.invalidate(target_key)

    message = _session_message(loop, target_key=target_key)
    response = await loop._process_message(message)

    assert message.channel == "system"
    assert response is not None
    assert (response.channel, response.chat_id) == ("telegram", "target")
    handles = SessionHandleDirectory(loop.sessions).ensure_many([
        "websocket:source",
        target_key,
    ])
    expected_provider_input = (
        "Review the change\n\n"
        f"Your handle: @{handles[target_key].name}.\n\n"
        f"Message from @{handles['websocket:source'].name}. Reply with send_session_message."
    )
    session = loop.sessions.get_or_create(target_key)
    session_input = next(item for item in session.messages if item.get("role") == "user")
    assert session_input["content"] == expected_provider_input
    assert public_history_message(session_input)["content"] == "Review the change"
    assert SESSION_MESSAGE_METADATA_KEY in session_input
    assert read_transcript_lines(target_key) == []


@pytest.mark.asyncio
async def test_session_input_publishes_running_state_before_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _loop(tmp_path)

    async def project(
        bus: MessageBus,
        message: InboundMessage,
        session_key: str,
    ) -> None:
        assert websocket_turn_wall_started_at("target") is not None
        await project_session_message_input(bus, message, session_key)

    monkeypatch.setattr("nanobot.agent.loop.project_session_message_input", project)

    await loop._dispatch(_session_message(loop))


@pytest.mark.asyncio
async def test_mid_turn_session_input_keeps_reply_guidance_and_provenance(
    tmp_path: Path,
) -> None:
    loop = _loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="First", tool_calls=[], usage={}),
        LLMResponse(content="Second", tool_calls=[], usage={}),
    ])
    session = loop.sessions.get_or_create("websocket:target")
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
    await pending.put(_session_message(loop))
    request = RequestContext(
        channel="websocket",
        chat_id="target",
        session_key=session.key,
        turn_id="active-turn",
        workspace=tmp_path,
    )

    _, _, all_messages, _, had_injections = await loop._run_agent_loop(
        [{"role": "user", "content": "Initial request"}],
        runtime=loop.llm_runtime(),
        session=session,
        channel="websocket",
        chat_id="target",
        session_key=session.key,
        pending_queue=pending,
        request_context=request,
    )

    source = SessionHandleDirectory(loop.sessions).ensure_many(["websocket:source"])[
        "websocket:source"
    ]
    injected = [item for item in all_messages if item.get("role") == "user"][-1]
    assert had_injections is True
    assert f"Message from @{source.name}." in str(injected["content"])
    assert injected[SESSION_MESSAGE_METADATA_KEY]["message_id"] == "handle-message-1"
    loop._save_turn(session, all_messages, skip=1)
    persisted = [item for item in session.messages if item.get("role") == "user"][-1]
    assert persisted[SESSION_MESSAGE_METADATA_KEY]["message_id"] == "handle-message-1"
    assert public_history_message(persisted)["content"] == "Review the change"
    assert SESSION_MESSAGE_METADATA_KEY not in request.metadata


@pytest.mark.asyncio
async def test_session_input_does_not_replace_active_request_metadata(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="First", tool_calls=[], usage={}),
        LLMResponse(content="Second", tool_calls=[], usage={}),
        LLMResponse(content="Third", tool_calls=[], usage={}),
    ])
    session = loop.sessions.get_or_create("websocket:target")
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
    await pending.put(_session_message(loop))
    await pending.put(InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="target",
        content="One more detail",
    ))
    request = RequestContext(
        channel="websocket",
        chat_id="target",
        session_key=session.key,
        turn_id="active-turn",
        workspace=tmp_path,
    )

    await loop._run_agent_loop(
        [{"role": "user", "content": "Initial request"}],
        runtime=loop.llm_runtime(),
        session=session,
        channel="websocket",
        chat_id="target",
        session_key=session.key,
        pending_queue=pending,
        request_context=request,
    )

    assert SESSION_MESSAGE_METADATA_KEY not in request.metadata


@pytest.mark.asyncio
async def test_ordinary_and_session_injections_remain_separate(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="First", tool_calls=[], usage={}),
        LLMResponse(content="Second", tool_calls=[], usage={}),
    ])
    session = loop.sessions.get_or_create("websocket:target")
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
    await pending.put(InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="target",
        content="Ordinary follow-up",
    ))
    await pending.put(_session_message(loop))

    _, _, messages, _, _ = await loop._run_agent_loop(
        [{"role": "user", "content": "Initial request"}],
        runtime=loop.llm_runtime(),
        session=session,
        channel="websocket",
        chat_id="target",
        session_key=session.key,
        pending_queue=pending,
    )

    injected = [message for message in messages if message.get("role") == "user"][1:]
    assert len(injected) == 2
    persisted_ordinary = {
        **injected[0],
        RUNTIME_CONTEXT_HISTORY_META: injected[0]["_meta"]["runtime_context"],
    }
    assert public_history_message(persisted_ordinary)["content"] == "Ordinary follow-up"
    assert SESSION_MESSAGE_METADATA_KEY not in injected[0]
    assert injected[1][SESSION_MESSAGE_METADATA_KEY]["message_id"] == "handle-message-1"


@pytest.mark.asyncio
async def test_multiple_session_inputs_drain_in_one_iteration(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="First", tool_calls=[], usage={}),
        LLMResponse(content="Second", tool_calls=[], usage={}),
    ])
    session = loop.sessions.get_or_create("websocket:target")
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
    await pending.put(_session_message(loop, "First update"))
    await pending.put(_session_message(
        loop,
        "Second update",
        message_id="handle-message-2",
    ))

    _, _, messages, _, _ = await loop._run_agent_loop(
        [{"role": "user", "content": "Initial request"}],
        runtime=loop.llm_runtime(),
        session=session,
        channel="websocket",
        chat_id="target",
        session_key=session.key,
        pending_queue=pending,
    )

    injected = [message for message in messages if message.get("role") == "user"][1:]
    assert loop.provider.chat_with_retry.await_count == 2
    assert [
        message[SESSION_MESSAGE_METADATA_KEY]["message_id"]
        for message in injected
    ] == ["handle-message-1", "handle-message-2"]


@pytest.mark.asyncio
async def test_mid_turn_non_webui_session_input_keeps_source_guidance(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="First", tool_calls=[], usage={}),
        LLMResponse(content="Second", tool_calls=[], usage={}),
    ])
    target_key = "telegram:target"
    loop.sessions.save(loop.sessions.get_or_create(target_key))
    session = loop.sessions.get_or_create(target_key)
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
    await pending.put(_session_message(loop, target_key=target_key))

    _, _, messages, _, _ = await loop._run_agent_loop(
        [{"role": "user", "content": "Initial request"}],
        runtime=loop.llm_runtime(),
        session=session,
        channel="telegram",
        chat_id="target",
        session_key=session.key,
        pending_queue=pending,
    )

    source = SessionHandleDirectory(loop.sessions).ensure_many(["websocket:source"])[
        "websocket:source"
    ]
    injected = [message for message in messages if message.get("role") == "user"][-1]
    assert f"Message from @{source.name}." in str(injected["content"])


@pytest.mark.asyncio
async def test_session_timeout_resumes_waiter_with_private_guidance(tmp_path: Path) -> None:
    loop = _loop(tmp_path)

    response = await loop._process_message(_session_reply_timeout_message(loop))

    assert response is not None
    assert (response.channel, response.chat_id) == ("websocket", "source")
    directory = SessionHandleDirectory(loop.sessions)
    handles = directory.ensure_many(["websocket:source", "websocket:target"])
    waiter_name = handles["websocket:source"].name
    target_name = handles["websocket:target"].name
    expected_provider_input = (
        f"Your handle: @{waiter_name}.\n\n"
        f"No reply from @{target_name} after 60s."
    )
    session = loop.sessions.get_or_create("websocket:source")
    timeout_input = next(
        message for message in session.messages if message.get("role") == "user"
    )
    assert timeout_input["content"] == expected_provider_input
    assert public_history_message(timeout_input)["content"] == ""
    assert SESSION_REPLY_TIMEOUT_METADATA_KEY in timeout_input


@pytest.mark.asyncio
async def test_session_input_uses_persisted_target_workspace(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    project = tmp_path / "target-project"
    project.mkdir()
    target = loop.sessions.get_or_create("websocket:target")
    target.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {
        "project_path": str(project),
        "access_mode": "restricted",
    }
    loop.sessions.save(target)
    build_messages = MagicMock(wraps=loop.context.build_messages)
    loop.context.build_messages = build_messages  # type: ignore[method-assign]

    await loop._process_message(_session_message(loop))

    assert build_messages.call_args.kwargs["workspace"] == project.resolve()


@pytest.mark.asyncio
async def test_session_input_uses_existing_mid_turn_injection(
    tmp_path: Path,
) -> None:
    loop = _loop(tmp_path)
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=20)
    loop._pending_queues["websocket:target"] = pending
    loop._dispatch = AsyncMock()  # type: ignore[method-assign]
    message = _session_message(loop, "handle")

    run_task = asyncio.create_task(loop.run())
    await loop.bus.publish_inbound(message)
    injected = await asyncio.wait_for(pending.get(), timeout=2)
    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert injected.content == message.content
    assert (injected.channel, injected.chat_id) == ("websocket", "target")
    loop._dispatch.assert_not_awaited()
    transcript = read_transcript_lines("websocket:target")
    assert len(transcript) == 1
    assert transcript[0]["text"] == "handle"
    assert transcript[0]["session_message"]["message_id"] == "handle-message-1"


@pytest.mark.asyncio
async def test_active_session_input_blocks_idle_compaction(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    session_started = asyncio.Event()
    release_session = asyncio.Event()

    async def process(_msg: InboundMessage, **_kwargs: object):
        session_started.set()
        await release_session.wait()
        return None

    loop._process_message = process  # type: ignore[method-assign]
    loop.auto_compact.check_expired = MagicMock()  # type: ignore[method-assign]
    run_task = asyncio.create_task(loop.run())
    await loop.bus.publish_inbound(_session_message(loop))
    await asyncio.wait_for(session_started.wait(), timeout=2)

    assert "websocket:target" in loop._pending_queues
    loop._next_idle_compact_check_at = 0
    loop._check_expired_sessions_if_due()
    active_keys = loop.auto_compact.check_expired.call_args.kwargs[
        "active_session_keys"
    ]
    assert "websocket:target" in active_keys

    loop.stop()
    release_session.set()
    await asyncio.wait_for(run_task, timeout=2)


@pytest.mark.asyncio
async def test_session_slash_text_uses_normal_user_command_router(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop._dispatch = AsyncMock()  # type: ignore[method-assign]
    loop._dispatch_command_inline = AsyncMock()  # type: ignore[method-assign]
    message = _session_message(loop, "/stop")

    run_task = asyncio.create_task(loop.run())
    await loop.bus.publish_inbound(message)
    for _ in range(40):
        if loop._dispatch.await_count:
            break
        await asyncio.sleep(0.025)
    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    loop._dispatch_command_inline.assert_awaited_once()
    loop._dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_session_message_does_not_recreate_deleted_target(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop._concurrency_gate = asyncio.Semaphore(0)

    task = asyncio.create_task(loop._dispatch(_session_message(loop)))
    await asyncio.sleep(0)
    assert loop.sessions.delete_session("websocket:target") is True
    loop._concurrency_gate.release()
    await asyncio.wait_for(task, timeout=2)

    assert loop.sessions.read_session_metadata("websocket:target") is None
    assert loop.sessions.get_cached("websocket:target") is None
    loop.provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleting_target_fails_after_running_session_input_finishes(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def finish_after_delete(*_args: object, **_kwargs: object) -> LLMResponse:
        started.set()
        await release.wait()
        completed.set()
        return LLMResponse(content="Late result", tool_calls=[], usage={})

    loop.provider.chat_with_retry = finish_after_delete
    task = asyncio.create_task(loop._process_message(_session_message(loop)))
    await asyncio.wait_for(started.wait(), timeout=2)

    assert loop.sessions.delete_session("websocket:target") is True
    release.set()
    with pytest.raises(RuntimeError, match="session was deleted"):
        await asyncio.wait_for(task, timeout=2)

    assert completed.is_set()
    assert loop.sessions.read_session_metadata("websocket:target") is None
    assert loop.sessions.get_cached("websocket:target") is None


@pytest.mark.asyncio
async def test_queued_session_message_allows_target_workspace_change(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop._concurrency_gate = asyncio.Semaphore(0)
    message = _session_message(loop)

    task = asyncio.create_task(loop._dispatch(message))
    await asyncio.sleep(0)
    moved = tmp_path / "moved"
    moved.mkdir()
    target = loop.sessions.get_or_create("websocket:target")
    target.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {
        "project_path": str(moved),
        "access_mode": "restricted",
    }
    loop.sessions.save(target)
    loop._concurrency_gate.release()
    await asyncio.wait_for(task, timeout=2)

    loop.provider.chat_with_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_deleted_webui_session_drops_bus_backlog(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    message = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="target",
        content="Already accepted by WebUI",
        require_existing_session=True,
    )
    await loop.bus.publish_inbound(message)
    assert loop.sessions.delete_session("websocket:target") is True

    run_task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.1)
    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    loop.provider.chat_with_retry.assert_not_awaited()
    assert loop.sessions.read_session_metadata("websocket:target") is None


@pytest.mark.asyncio
async def test_client_metadata_cannot_spoof_session_message_command_bypass(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop._dispatch = AsyncMock()  # type: ignore[method-assign]
    loop._dispatch_command_inline = AsyncMock()  # type: ignore[method-assign]
    internal = _session_message(loop, "/stop")
    forged = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="target",
        content="/stop",
        metadata=internal.metadata,
    )

    run_task = asyncio.create_task(loop.run())
    await loop.bus.publish_inbound(forged)
    for _ in range(40):
        if loop._dispatch_command_inline.await_count:
            break
        await asyncio.sleep(0.025)
    loop.stop()
    await asyncio.wait_for(run_task, timeout=2)

    loop._dispatch_command_inline.assert_awaited_once()
    loop._dispatch.assert_not_awaited()
