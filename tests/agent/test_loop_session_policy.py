import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from agent.session_helpers import run_session
from nanobot.agent.context import TranscriptInput
from nanobot.agent.loop import AgentLoop
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent_sessions import SubagentSessions
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_SESSION_DISCARD,
    InboundMessage,
)
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.runtime_context import RuntimeContextBlock
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.session.manager import SessionPolicy
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.webui.temporary_chats import WebUITemporaryChats
from nanobot.webui.workspaces import WebUIWorkspaceController


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
    provider = MagicMock(aclose=AsyncMock())
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


@pytest.mark.parametrize("restriction", ["none", "session", "request"])
async def test_delegation_preserves_disabled_tools(tmp_path, monkeypatch, restriction) -> None:
    monkeypatch.setattr("nanobot.agent.tools.loader.entry_points", lambda **kwargs: [])
    loop = _loop(tmp_path, [], context_window_tokens=128_000)
    loop.provider.estimate_prompt_tokens.return_value = (1000, "test")
    key = "cli:delegation-policy"
    session = loop.sessions.get_or_create(key)
    policy = SessionPolicy(disabled_tools=frozenset({"write_file"}))
    if restriction == "session":
        session.policy = policy
    calls = {"parent": 0, "child": 0}
    definitions = {}
    results = {}

    async def respond(**kwargs):
        ctx = current_request_context()
        who = "child" if ctx.session_key.startswith("subagent:") else "parent"
        calls[who] += 1
        definitions[who] = {tool["function"]["name"] for tool in kwargs["tools"]}
        results[who] = [msg["content"] for msg in kwargs["messages"] if msg["role"] == "tool"]
        if calls[who] == 1:
            return LLMResponse(content="", tool_calls=[ToolCallRequest(
                id=f"{who}-write", name="write_file",
                arguments={"path": f"{who}.txt", "content": f"Written by {who}"},
            )])
        if who == "parent" and calls[who] == 2:
            return LLMResponse(content="", tool_calls=[ToolCallRequest(
                id="delegate", name="subagent",
                arguments={"action": "create", "task": "Write child.txt", "wait": True},
            )])
        return LLMResponse(content="Done.")

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    try:
        response = await loop.process_direct(
            "Write a file, then delegate a file write.", session_key=key,
            _session_policy=policy if restriction == "request" else None,
        )
        assert response is not None and response.content == "Done."
        for who in ("parent", "child"):
            output = tmp_path / f"{who}.txt"
            if restriction == "none":
                assert "write_file" in definitions[who]
                assert output.read_text(encoding="utf-8") == f"Written by {who}"
            else:
                assert not output.exists()
                assert "write_file" not in definitions[who]
                assert "Tool 'write_file' not found" in results[who][0]
    finally:
        await loop.aclose()


async def test_background_subagent_combines_parent_and_requested_tool_restrictions(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.agent.tools.loader.entry_points", lambda **kwargs: [])
    loop = _loop(tmp_path, [], context_window_tokens=128_000)
    loop.provider.estimate_prompt_tokens.return_value = (1000, "test")
    key = "cli:background-policy"
    session = loop.sessions.get_or_create(key)
    session.policy = SessionPolicy(disabled_tools=frozenset({"write_file"}))
    source = tmp_path / "source.txt"
    source.write_text("original", encoding="utf-8")
    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[
            ToolCallRequest(id="write", name="write_file", arguments={
                "path": "child.txt", "content": "unexpected",
            }),
            ToolCallRequest(id="edit", name="edit_file", arguments={
                "path": "source.txt", "old_text": "original", "new_text": "unexpected",
            }),
            ToolCallRequest(id="read", name="read_file", arguments={"path": "source.txt"}),
        ]),
        LLMResponse(content="Done."),
    ])
    try:
        await loop.subagents.spawn(
            "Write, edit, and read files.", session_key=key,
            runtime=LLMRuntime.capture(loop.provider, "test-model", context_window_tokens=128_000),
            session_policy=SessionPolicy(disabled_tools=frozenset({"edit_file"})),
        )
        await asyncio.wait_for(asyncio.gather(*loop.subagents._running_tasks.values()), timeout=10)
        assert not (tmp_path / "child.txt").exists()
        assert source.read_text(encoding="utf-8") == "original"
        requests = loop.provider.chat_stream_with_retry.await_args_list
        assert len(requests) == 2
        names = {tool["function"]["name"] for tool in requests[0].kwargs["tools"]}
        assert {"write_file", "edit_file"}.isdisjoint(names)
        assert "read_file" in names
        results = {
            msg["tool_call_id"]: msg["content"]
            for msg in requests[1].kwargs["messages"] if msg["role"] == "tool"
        }
        assert "Tool 'write_file' not found" in results["write"]
        assert "Tool 'edit_file' not found" in results["edit"]
        assert "original" in results["read"]
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_transient_session_keeps_history_without_persisting_or_durable_tools(tmp_path) -> None:
    loop = _loop(tmp_path, ["first answer", "second answer"])
    loop.context.memory.write_memory("private durable memory")
    temporary_chats = WebUITemporaryChats(
        bus=loop.bus, session_manager=loop.sessions, logger=logger,
        workspaces=WebUIWorkspaceController(
            session_manager=loop.sessions, default_workspace=tmp_path,
            default_restrict_to_workspace=True,
        ),
    )
    key = f"websocket:{temporary_chats.create(object(), trusted_webui=True)}"

    await loop._process_message(_message(key, "first question"))
    await loop._process_message(_message(key, "second question"))

    calls = loop.provider.chat_stream_with_retry.await_args_list
    assert "private durable memory" not in str(calls[0].kwargs["messages"])
    tool_names = {item["function"]["name"] for item in calls[0].kwargs["tools"]}
    assert "read_session" in tool_names
    assert {"create_goal", "update_goal", "subagent", "cron"}.isdisjoint(tool_names)
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
    temporary_chats.close()
    await loop.aclose()


@pytest.mark.parametrize("selection", ["explicit_empty", "disable_all", "default"])
async def test_turn_tool_selection_preserves_empty_registries(tmp_path, monkeypatch, selection) -> None:
    monkeypatch.setattr("nanobot.agent.tools.loader.entry_points", lambda **kwargs: [])
    loop = _loop(tmp_path, [], max_iterations=2)
    key = "cli:tool-selection"
    write_tool = loop.tools.get("write_file")
    assert write_tool is not None
    tool_context = RuntimeContextBlock(source="write_file", content="Write tool runtime context")
    provide_context = AsyncMock(return_value=tool_context)
    monkeypatch.setattr(write_tool, "runtime_context_provider", lambda: provide_context)
    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[
            ToolCallRequest(
                id="write-1", name="write_file",
                arguments={"path": "result.txt", "content": "tool executed"},
            ),
        ]),
        LLMResponse(content="done"),
    ])
    kwargs = {}
    if selection == "explicit_empty":
        kwargs["tools"] = ToolRegistry()
    elif selection == "disable_all":
        session = loop.sessions.get_or_create(key)
        session.policy = SessionPolicy(disabled_tools=frozenset(loop.tools.tool_names))

    try:
        response = await loop.process_direct("Handle this request", session_key=key, **kwargs)

        assert response is not None and response.content == "done"
        requests = loop.provider.chat_stream_with_retry.await_args_list
        assert len(requests) == 2
        allowed = selection == "default"
        expected_names = set(loop.tools.tool_names) if allowed else set()
        for request in requests:
            assert {item["function"]["name"] for item in request.kwargs["tools"]} == expected_names
            assert (tool_context.content in str(request.kwargs["messages"])) is allowed
        tool_result = next(
            message for message in requests[1].kwargs["messages"]
            if message.get("role") == "tool"
        )
        assert tool_result["tool_call_id"] == "write-1"
        output_file = tmp_path / "result.txt"
        if allowed:
            provide_context.assert_awaited_once()
            assert output_file.read_text(encoding="utf-8") == "tool executed"
            assert "Successfully wrote" in tool_result["content"]
        else:
            provide_context.assert_not_awaited()
            assert not output_file.exists()
            assert "Tool 'write_file' not found" in tool_result["content"]
    finally:
        await loop.aclose()


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
async def test_required_durable_session_survives_cache_eviction(tmp_path) -> None:
    loop = _loop(tmp_path, ["received"])
    key = "websocket:durable-parent"
    session = loop.sessions.get_or_create(key)
    session.add_message("user", "earlier question")
    loop.sessions.save(session)
    loop.sessions.invalidate(key)
    try:
        response = await loop._process_message(_message(key, "follow-up"))
        assert response is not None and response.content == "received"
        assert "earlier question" in str(loop.provider.chat_stream_with_retry.await_args.kwargs["messages"])
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_deleted_child_cannot_notify_a_recreated_parent(tmp_path) -> None:
    loop = _loop(tmp_path, [])
    key = "websocket:recreated-parent"
    loop.subagents.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="old result"))
    try:
        await loop.subagents.spawn("old task", session_key=key, runtime=loop.llm_runtime())
        await asyncio.gather(*loop.subagents._running_tasks.values())
        task_id, = loop.subagents.statuses_for_session(key)
        notice = await asyncio.wait_for(loop.bus.consume_inbound(), timeout=2)
        assert notice.require_existing_session
        assert loop.sessions.delete_session(key)
        assert loop.sessions.read_session_file(SubagentSessions.key(task_id)) is None
        loop.sessions.save(loop.sessions.get_or_create(key))

        assert loop.subagents.statuses_for_session(key) == {}
        loop._enqueue_session_message(notice)
        assert key not in loop._pending_queues
        assert await loop._process_message(notice) is None
        loop.provider.chat_stream_with_retry.assert_not_awaited()
        assert loop.sessions.read_session_file(key)["messages"] == []
    finally:
        await loop.aclose()


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
        disabled_tools={"create_goal", "update_goal", "subagent", "cron"},
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
