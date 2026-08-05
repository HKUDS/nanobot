import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_MEMORY_ONLY_SESSION_DISCARD,
    InboundMessage,
)
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.session.policy import MEMORY_ONLY_SESSION_RUNTIME_POLICY
from nanobot.triggers.local_store import LocalTriggerStore


def _message(key: str, content: str) -> InboundMessage:
    return InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id=key.removeprefix("websocket:"),
        content=content,
        session_key_override=key,
        required_session_policy=MEMORY_ONLY_SESSION_RUNTIME_POLICY,
    )


@pytest.mark.asyncio
async def test_temporary_chat_keeps_agent_capabilities_and_only_live_history(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("project instruction", encoding="utf-8")
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="first answer", usage={}),
        LLMResponse(content="second answer", usage={}),
    ])
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        cron_service=MagicMock(),
    )
    loop.context.memory.write_memory("# Memory\n- private remembered detail")
    key = "websocket:temporary-test"
    loop.sessions.get_or_create_memory_only(key)

    await loop._process_message(_message(key, "first question"))
    await loop._process_message(_message(key, "second question"))

    first_call, second_call = provider.chat_with_retry.await_args_list
    tool_names = {
        definition["function"]["name"]
        for definition in first_call.kwargs["tools"]
    }
    assert "read_session" in tool_names
    assert {"create_goal", "update_goal", "spawn", "cron"}.isdisjoint(tool_names)
    assert "project instruction" in str(first_call.kwargs["messages"])
    assert "private remembered detail" not in str(first_call.kwargs["messages"])
    assert "first answer" in str(second_call.kwargs["messages"])
    session = loop.sessions.get_cached(key)
    assert session is not None
    assert [message["role"] for message in session.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_temporary_chat_compacts_only_in_memory(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=256)
    provider.estimate_prompt_tokens.return_value = (100, "test")
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="Earlier temporary decisions.", usage={})
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=4096,
    )
    key = "websocket:temporary-compact"
    session = loop.sessions.get_or_create_memory_only(key)
    for index in range(6):
        session.add_message("user", f"question {index}")
        session.add_message("assistant", f"answer {index}")

    await loop.consolidator.maybe_consolidate_by_tokens(
        session,
        runtime=loop.runtime_for_session(session),
        replay_max_messages=4,
    )

    assert session.last_consolidated > 0
    assert len(session.messages) == 12
    assert session.metadata["_last_summary"]["text"] == "Earlier temporary decisions."
    assert loop.sessions.read_session_file(key) is None
    assert loop.context.memory.read_unprocessed_history(since_cursor=0) == []
    _, summary = loop.auto_compact.prepare_session(session, key)
    assert summary is not None


@pytest.mark.asyncio
async def test_temporary_chat_uses_the_regular_compaction_pipeline(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="answer", usage={})
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
    key = "websocket:temporary-pipeline"
    loop.sessions.get_or_create_memory_only(key)

    await loop._process_message(_message(key, "question"))

    loop.consolidator.maybe_consolidate_by_tokens.assert_awaited()


@pytest.mark.asyncio
async def test_discarded_temporary_turn_cannot_create_a_session_file(tmp_path) -> None:
    provider_started = asyncio.Event()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()

    async def block_provider(**_kwargs):
        provider_started.set()
        await asyncio.Event().wait()

    provider.chat_with_retry = AsyncMock(side_effect=block_provider)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    key = "websocket:temporary-cancelled"
    loop.sessions.get_or_create_memory_only(key)
    task = asyncio.create_task(loop._dispatch(_message(key, "private")))
    loop._active_tasks.setdefault(key, set()).add(task)

    await provider_started.wait()
    assert await loop._cancel_active_tasks(key) == 1
    assert loop.sessions.discard_memory_only(key) is True

    assert task.cancelled()
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_temporary_chat_new_clears_history_without_archiving_or_losing_policy(
    tmp_path,
) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="answer after reset", usage={})
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.schedule_background = MagicMock()
    key = "websocket:temporary-new"
    session = loop.sessions.get_or_create_memory_only(key)
    session.add_message("user", "private question before reset")
    session.add_message("assistant", "private answer before reset")

    response = await loop._process_message(_message(key, "/new"))

    assert response is not None
    assert response.content == "New session started."
    assert loop.sessions.get_cached(key) is session
    assert session.is_memory_only is True
    assert session.messages == []
    loop.schedule_background.assert_not_called()

    await loop._process_message(_message(key, "question after reset"))

    assert [message["content"] for message in session.messages] == [
        "question after reset",
        "answer after reset",
    ]
    assert loop.sessions.read_session_file(key) is None
    assert loop.context.memory.read_unprocessed_history(since_cursor=0) == []


@pytest.mark.asyncio
async def test_temporary_chat_stays_isolated_when_unified_session_is_enabled(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="private answer", usage={})
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        unified_session=True,
    )
    durable = loop.sessions.get_or_create(UNIFIED_SESSION_KEY)
    durable.add_message("user", "durable question")
    loop.sessions.save(durable)
    key = "websocket:temporary-unified"
    memory_only = loop.sessions.get_or_create_memory_only(key)

    await loop._dispatch(_message(key, "private question"))

    assert [message["content"] for message in memory_only.messages] == [
        "private question",
        "private answer",
    ]
    assert [message["content"] for message in durable.messages] == ["durable question"]
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_temporary_chat_rejects_session_bound_deferred_work(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock()
    trigger_store = LocalTriggerStore(tmp_path)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        local_trigger_store=trigger_store,
    )
    key = "websocket:temporary-deferred-work"
    session = loop.sessions.get_or_create_memory_only(key)

    goal_response = await loop._process_message(_message(key, "/goal private goal"))
    trigger_response = await loop._process_message(_message(key, "/trigger private trigger"))

    assert goal_response is not None
    assert goal_response.content == (
        "Goal mode requires a persistent chat. Open a regular chat and try again."
    )
    assert trigger_response is not None
    assert trigger_response.content == (
        "Triggers require a persistent chat. Open a regular chat and try again."
    )
    assert "goal_state" not in session.metadata
    assert trigger_store.list_for_session(key) == []
    provider.chat_with_retry.assert_not_awaited()
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_discard_cancels_a_turn_before_session_restore(tmp_path, monkeypatch) -> None:
    restore_started = asyncio.Event()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    key = "websocket:temporary-before-restore"
    loop.sessions.get_or_create_memory_only(key)

    async def block_restore(_ctx) -> None:
        restore_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(loop, "_restore_turn", block_restore)
    task = asyncio.create_task(loop._dispatch(_message(key, "private-race-content")))
    loop._active_tasks.setdefault(key, set()).add(task)

    await restore_started.wait()
    assert await loop._cancel_active_tasks(key) == 1
    assert loop.sessions.discard_memory_only(key) is True

    assert task.cancelled()
    assert loop.sessions.get_cached(key) is None
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_runtime_discard_drops_pending_messages_before_releasing_session(tmp_path) -> None:
    provider_started = asyncio.Event()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()

    async def block_provider(**_kwargs):
        provider_started.set()
        await asyncio.Event().wait()

    provider.chat_with_retry = AsyncMock(side_effect=block_provider)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop._connect_mcp = AsyncMock()
    loop.close_mcp = AsyncMock()
    loop._exec_session_manager.terminate_by_owner = AsyncMock(return_value=0)
    key = "websocket:temporary-pending-discard"
    loop.sessions.get_or_create_memory_only(key)
    loop._file_state_store.for_session(key)
    run_task = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(_message(key, "first private message"))
        await provider_started.wait()
        await loop.bus.publish_inbound(_message(key, "queued private message"))
        for _ in range(100):
            pending = loop._pending_queues.get(key)
            if pending is not None and not pending.empty():
                break
            await asyncio.sleep(0.01)
        assert pending is not None and pending.qsize() == 1

        await loop.bus.publish_inbound(InboundMessage(
            channel="websocket",
            sender_id="webui",
            chat_id=key.removeprefix("websocket:"),
            content="",
            session_key_override=key,
            required_session_policy=MEMORY_ONLY_SESSION_RUNTIME_POLICY,
            metadata={
                INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_MEMORY_ONLY_SESSION_DISCARD,
            },
        ))
        for _ in range(100):
            if not loop.sessions.is_memory_only_active(key):
                break
            await asyncio.sleep(0.01)

        assert loop.sessions.is_memory_only_active(key) is False
        assert loop.bus.inbound_size == 0
        assert loop.sessions.read_session_file(key) is None
        assert loop._file_state_store.discard(key) is False
        loop._exec_session_manager.terminate_by_owner.assert_awaited_once_with(key)
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=2)


@pytest.mark.asyncio
async def test_runtime_discard_retains_memory_only_policy_when_cleanup_fails(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    key = "websocket:temporary-cleanup-failure"
    session = loop.sessions.get_or_create_memory_only(key)
    session.add_message("user", "private content")
    loop._cancel_active_tasks = AsyncMock(side_effect=RuntimeError("cancel failed"))
    loop._exec_session_manager.terminate_by_owner = AsyncMock(return_value=0)

    await loop._discard_memory_only_session(key)

    assert loop.sessions.get_cached(key) is session
    assert loop.sessions.is_memory_only_active(key) is True
    loop.sessions.save(session, fsync=True)
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_runtime_discard_fails_all_kinds_of_deferred_turns(tmp_path) -> None:
    from nanobot.agent.automation_turns import AutomationTurnError
    from nanobot.cron.session_turns import CRON_TRIGGER_META
    from nanobot.triggers.local_session_turns import LOCAL_TRIGGER_META

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    key = "websocket:temporary-deferred-cleanup"
    loop.sessions.get_or_create_memory_only(key)
    loop._running = True
    cron_message = InboundMessage(
        channel="websocket",
        sender_id="cron",
        chat_id="temporary-deferred-cleanup",
        content="cron work",
        session_key_override=key,
        metadata={CRON_TRIGGER_META: {"job_id": "job-1", "run_id": "run-1"}},
    )
    trigger_message = InboundMessage(
        channel="websocket",
        sender_id="trigger",
        chat_id="temporary-deferred-cleanup",
        content="trigger work",
        session_key_override=key,
        metadata={
            LOCAL_TRIGGER_META: {
                "trigger_id": "trigger-1",
                "trigger_name": "review",
                "delivery_id": "delivery-1",
            },
        },
    )
    cron_task = asyncio.create_task(loop.submit_cron_turn(cron_message))
    trigger_task = asyncio.create_task(loop.submit_local_trigger_turn(trigger_message))
    published = [
        await asyncio.wait_for(loop.bus.consume_inbound(), timeout=0.5),
        await asyncio.wait_for(loop.bus.consume_inbound(), timeout=0.5),
    ]
    loop._deferred_automation_turns[key] = published

    await loop._discard_memory_only_session(key)

    with pytest.raises(AutomationTurnError):
        await cron_task
    with pytest.raises(AutomationTurnError):
        await trigger_task
    assert key not in loop._deferred_automation_turns
    assert loop.sessions.is_memory_only_active(key) is False


@pytest.mark.asyncio
async def test_stale_message_after_discard_cannot_recreate_a_durable_session(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop._connect_mcp = AsyncMock()
    loop.close_mcp = AsyncMock()
    key = "websocket:temporary-stale-message"
    loop.sessions.get_or_create_memory_only(key)
    run_task = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(InboundMessage(
            channel="websocket",
            sender_id="webui",
            chat_id=key.removeprefix("websocket:"),
            content="",
            session_key_override=key,
            required_session_policy=MEMORY_ONLY_SESSION_RUNTIME_POLICY,
            metadata={
                INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_MEMORY_ONLY_SESSION_DISCARD,
            },
        ))
        await loop.bus.publish_inbound(_message(key, "stale private message"))
        for _ in range(100):
            if not loop.sessions.is_memory_only_active(key) and loop.bus.inbound_size == 0:
                break
            await asyncio.sleep(0.01)

        assert loop.sessions.get_cached(key) is None
        assert loop.sessions.read_session_file(key) is None
        provider.chat_with_retry.assert_not_awaited()
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=2)


@pytest.mark.asyncio
async def test_memory_only_turn_omits_message_and_response_content_from_logs(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(
                id="call-1",
                name="list_dir",
                arguments={"path": "private-tool-argument"},
            )],
            finish_reason="tool_calls",
            usage={},
        ),
        LLMResponse(content="private-response-content", usage={}),
    ])
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    key = "websocket:temporary-log-redaction"
    loop.sessions.get_or_create_memory_only(key)
    records: list[str] = []
    sink = logger.add(records.append, format="{message}")
    try:
        await loop._process_message(_message(key, "private-request-content"))
    finally:
        logger.remove(sink)

    logs = "".join(records)
    assert "private-request-content" not in logs
    assert "private-response-content" not in logs
    assert "private-tool-argument" not in logs
    assert "[content omitted]" in logs
    assert "[arguments omitted]" in logs
    assert all(
        call.kwargs["provider_context"].log_content is False
        for call in provider.chat_with_retry.await_args_list
    )
