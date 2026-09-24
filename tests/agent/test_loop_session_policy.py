import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from agent.session_helpers import run_session
from nanobot.agent.context import TranscriptInput
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import current_request_context
from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_SESSION_DISCARD,
    InboundMessage,
)
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.session.manager import SessionPolicy


def _message(key: str, content: str) -> InboundMessage:
    return InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id=key.removeprefix("websocket:"),
        content=content,
        session_key_override=key,
        require_existing_session=True,
    )


def _loop(tmp_path, responses: list[str], **kwargs) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_stream_with_retry = AsyncMock(
        side_effect=[LLMResponse(content=response, usage=None) for response in responses]
    )
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        cron_service=MagicMock(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_transient_session_keeps_history_without_persisting_or_durable_tools(tmp_path) -> None:
    loop = _loop(tmp_path, ["first answer", "second answer"])
    loop.context.memory.write_memory("private durable memory")
    key = "websocket:transient-test"
    loop.sessions.get_or_create_transient(
        key,
        disabled_tools={"create_goal", "update_goal", "spawn", "cron"},
    )

    await loop._process_message(_message(key, "first question"))
    await loop._process_message(_message(key, "second question"))

    calls = loop.provider.chat_stream_with_retry.await_args_list
    assert "private durable memory" not in str(calls[0].kwargs["messages"])
    tool_names = {item["function"]["name"] for item in calls[0].kwargs["tools"]}
    assert "read_session" in tool_names
    assert {"create_goal", "update_goal", "spawn", "cron"}.isdisjoint(tool_names)
    assert "first answer" in str(calls[1].kwargs["messages"])
    session = loop.sessions.get_cached(key)
    assert session is not None
    assert [message["role"] for message in session.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.parametrize("privacy", ["temporary", "quiet", "ordinary"])
@pytest.mark.parametrize("structured", [True, False])
async def test_session_policy_controls_tool_logs_and_result_offload(
    tmp_path, privacy, structured,
) -> None:
    loop = _loop(tmp_path, [])
    loop.max_tool_result_chars = 2048
    key = "websocket:privacy-regression"
    if privacy == "temporary":
        loop.sessions.get_or_create_transient(key)
    else:
        session = loop.sessions.get_or_create(key)
        session.policy = SessionPolicy(log_content=privacy != "quiet")
    secret = "synthetic-private-query-测试"
    text = "synthetic-private-result-" * 1000
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,c3ludGhldGlj"}}
    result = [{"type": "text", "text": text}, image] if structured else text
    loop.tools.prepare_call = MagicMock(return_value=(None, {"query": secret}, None))
    loop.tools.execute = AsyncMock(return_value=result)
    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[
            ToolCallRequest(id="private_result", name="web_search", arguments={"query": secret}),
        ]),
        LLMResponse(content="done"),
    ])
    logs: list[str] = []
    sink = logger.add(lambda message: logs.append(str(message)), format="{message}")
    try:
        await loop._process_message(_message(key, "synthetic question"))
    finally:
        logger.remove(sink)

    assert loop.tools.execute.await_count == 1
    messages = loop.provider.chat_stream_with_retry.await_args.kwargs["messages"]
    content = next(m["content"] for m in messages if m["role"] == "tool")
    preview = content[0]["text"] if structured else content
    offload_root = tmp_path / ".nanobot" / "tool-results"
    assert (secret in "\n".join(logs)) is (privacy == "ordinary")
    if structured:
        assert content[1] == image
    if privacy == "temporary":
        assert not offload_root.exists()
        assert preview.endswith("... (truncated)")
        assert len(preview) < len(text)
        await loop.discard_session(key)
        assert loop.sessions.get_cached(key) is None
        assert loop.sessions.read_session_file(key) is None
        assert not offload_root.exists()
    else:
        assert "[tool output persisted]" in preview
        assert [p.read_text() for p in offload_root.rglob("*.txt")] == [text]


async def test_direct_transient_run_never_spills_before_cancellation(tmp_path) -> None:
    loop = _loop(tmp_path, [])
    session = loop.sessions.get_or_create_transient("websocket:cancel-private")
    loop.max_tool_result_chars = 100
    loop.tools.prepare_call = MagicMock(return_value=(None, {}, None))
    loop.tools.execute = AsyncMock(return_value="synthetic large result" * 1000)
    second_call = asyncio.Event()
    count = 0

    async def respond(**kwargs):
        nonlocal count
        count += 1
        request = current_request_context()
        assert request is not None and request.workspace == tmp_path
        assert request.log_content is False
        if count == 1:
            return LLMResponse(content="", tool_calls=[
                ToolCallRequest(id="cancel-result", name="web_search", arguments={}),
            ])
        second_call.set()
        await asyncio.Event().wait()

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    # The session policy must suffice even without passing ephemeral=True.
    task = asyncio.create_task(loop._run_agent_loop(
        TranscriptInput(history=[], current_message="synthetic question"),
        runtime=loop.llm_runtime(), session=session,
    ))
    try:
        await asyncio.wait_for(second_call.wait(), timeout=2)
        assert not (tmp_path / ".nanobot" / "tool-results").exists()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await loop.discard_session(session.key)
    assert not (tmp_path / ".nanobot" / "tool-results").exists()
    assert current_request_context() is None


@pytest.mark.parametrize("private", [True, False])
@pytest.mark.parametrize("failure", ["runner", "discard", "queue"])
async def test_session_worker_errors_keep_private_content_out_of_logs(
    tmp_path, private, failure, monkeypatch,
) -> None:
    loop = _loop(tmp_path, [])
    key = "websocket:synthetic-worker-error"
    if private:
        loop.sessions.get_or_create_transient(key)
    else:
        loop.sessions.get_or_create(key)
    secret = "synthetic-private-worker-content"
    if failure == "runner":
        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=ValueError(secret))
    else:
        async def fail_after_discard(*args, **kwargs):
            # The privacy snapshot must survive cache eviction during failure.
            loop.sessions.invalidate(key)
            raise ValueError(secret)

        target = "_process_message" if failure == "discard" else "_dispatch_one"
        monkeypatch.setattr(loop, target, fail_after_discard)
    records = []
    sink = logger.add(lambda message: records.append(message.record), format="{message}")
    try:
        await run_session(loop, _message(key, secret))
    finally:
        logger.remove(sink)
    errors = [r for r in records if r["level"].name == "ERROR"]
    assert errors
    assert all(r["exception"] is None for r in errors) is private
    if private:
        assert secret not in str([r["message"] for r in records])


@pytest.mark.asyncio
async def test_transient_session_stays_outside_unified_session(tmp_path) -> None:
    loop = _loop(tmp_path, ["private answer"], unified_session=True)
    durable = loop.sessions.get_or_create(UNIFIED_SESSION_KEY)
    durable.add_message("user", "durable question")
    loop.sessions.save(durable)
    key = "websocket:transient-unified"
    transient = loop.sessions.get_or_create_transient(key)

    await run_session(loop, _message(key, "private question"))

    assert [message["content"] for message in transient.messages] == [
        "private question",
        "private answer",
    ]
    assert [message["content"] for message in durable.messages] == ["durable question"]
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_missing_required_session_cannot_fall_back_to_disk(tmp_path) -> None:
    loop = _loop(tmp_path, [])
    key = "websocket:transient-stale"
    loop.sessions.get_or_create_transient(key)
    loop.sessions.invalidate(key)

    with pytest.raises(RuntimeError, match="required session is not active"):
        await loop._process_message(_message(key, "stale private message"))

    loop.provider.chat_stream_with_retry.assert_not_awaited()
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_session_discard_control_cancels_active_turn(tmp_path, monkeypatch) -> None:
    provider_started = asyncio.Event()

    async def block_provider(**_kwargs: object) -> LLMResponse:
        provider_started.set()
        await asyncio.Event().wait()
        raise AssertionError("provider blocker unexpectedly released")

    loop = _loop(tmp_path, [])

    async def wait_for_discard(key: str) -> None:
        while loop.sessions.get_cached(key) is not None or key in loop._discarding_sessions:
            await asyncio.sleep(0)

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=block_provider)
    monkeypatch.setattr(loop, "aclose", AsyncMock())
    terminate_exec_sessions = AsyncMock(return_value=1)
    monkeypatch.setattr(
        loop._exec_session_manager,
        "terminate_by_owner",
        terminate_exec_sessions,
    )
    key = "websocket:transient-cancelled"
    previous_file_state = loop._file_state_store.for_session(key)
    loop.sessions.get_or_create_transient(
        key,
        disabled_tools={"create_goal", "update_goal", "spawn", "cron"},
    )
    run_task = asyncio.create_task(loop.run())
    await loop.bus.publish_inbound(_message(key, "private"))
    await asyncio.wait_for(provider_started.wait(), timeout=2)
    active_task = next(iter(loop._active_tasks[key]))

    await loop.bus.publish_inbound(
        InboundMessage(
            channel="websocket",
            sender_id="webui",
            chat_id="transient-cancelled",
            content="",
            metadata={
                INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_SESSION_DISCARD,
            },
            session_key_override=key,
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(active_task, timeout=2)
    await asyncio.wait_for(wait_for_discard(key), timeout=2)
    assert loop.sessions.get_cached(key) is None
    assert loop._file_state_store.for_session(key) is not previous_file_state
    terminate_exec_sessions.assert_awaited_once_with(key)

    loop.stop()
    await loop.bus.publish_inbound(_message(key, "wake"))
    await asyncio.wait_for(run_task, timeout=2)
