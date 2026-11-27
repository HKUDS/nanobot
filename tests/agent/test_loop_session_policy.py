import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from agent.session_helpers import make_agent_loop, run_session
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
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.runtime_context import RuntimeContextBlock
from nanobot.session.manager import SessionPolicy
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
    return make_agent_loop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        cron_service=MagicMock(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_transient_session_keeps_history_without_persisting_or_durable_tools(tmp_path) -> None:
    loop = _loop(tmp_path, ["first answer", "second answer", "ordinary answer"])
    loop.context.memory.write_memory("private durable memory")
    (tmp_path / "SOUL.md").write_text("private agent profile", encoding="utf-8")
    (tmp_path / "USER.md").write_text("private user profile", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("shared project guidance", encoding="utf-8")
    helper = tmp_path / "skills" / "helper" / "SKILL.md"
    helper.parent.mkdir(parents=True)
    helper.write_text("---\nname: helper\ndescription: Project helper\n---\nProject helper procedure", encoding="utf-8")
    memory_skill = tmp_path / "skills" / "memory" / "SKILL.md"
    memory_skill.parent.mkdir()
    memory_skill.write_text("---\nname: memory\ndescription: Memory skill discovery cue\n---\nMemory skill body", encoding="utf-8")
    temporary_chats = WebUITemporaryChats(
        bus=loop.bus, session_manager=loop.sessions, logger=logger,
        workspaces=WebUIWorkspaceController(
            session_manager=loop.sessions, default_workspace=tmp_path,
            default_restrict_to_workspace=True,
        ),
    )
    key = f"websocket:{await temporary_chats.create(object(), trusted_webui=True)}"

    await loop._process_message(_message(key, "first question $memory $helper $cron"))
    await loop._process_message(_message(key, "second question"))
    await loop.process_direct("ordinary question $memory $helper $cron", session_key="cli:ordinary")

    calls = loop.provider.chat_stream_with_retry.await_args_list
    private_markers = (
        "private durable memory", "private agent profile", "private user profile",
        "Memory skill discovery cue", "Memory skill body", "memory/wiki/index.md",
    )
    for call in calls[:2]:
        provider_context = str(call.kwargs["messages"])
        assert all(marker not in provider_context for marker in private_markers)
        assert "shared project guidance" in provider_context
    transient_messages = calls[0].kwargs["messages"]
    ordinary_messages = calls[2].kwargs["messages"]
    assert "Project helper procedure" in str(transient_messages)
    assert all(marker in str(ordinary_messages) for marker in private_markers)
    assert "Scheduling is unavailable" in transient_messages[0]["content"]
    assert "cron/SKILL.md" not in transient_messages[0]["content"]
    assert "## Update a Task" not in transient_messages[-1]["content"]
    assert "cron/SKILL.md" in ordinary_messages[0]["content"]
    assert "## Update a Task" in ordinary_messages[-1]["content"]
    tool_names = {item["function"]["name"] for item in calls[0].kwargs["tools"]}
    assert "read_session" in tool_names
    assert {"create_goal", "update_goal", "subagent", "cron"}.isdisjoint(tool_names)
    assert "subagent" in {item["function"]["name"] for item in calls[2].kwargs["tools"]}
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


async def test_temporary_chat_does_not_execute_unadvertised_subagent_call(tmp_path) -> None:
    loop = _loop(tmp_path, [])
    chats = WebUITemporaryChats(
        bus=loop.bus, session_manager=loop.sessions, logger=logger,
        workspaces=WebUIWorkspaceController(
            session_manager=loop.sessions, default_workspace=tmp_path,
            default_restrict_to_workspace=True,
        ),
    )
    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[ToolCallRequest(
            id="delegate", name="subagent", arguments={"action": "create", "task": "Synthetic task", "wait": True},
        )]),
        LLMResponse(content="Done without delegating."),
    ])
    try:
        key = f"websocket:{await chats.create(object(), trusted_webui=True)}"
        await loop._process_message(_message(key, "Do a small task."))
        calls = loop.provider.chat_stream_with_retry.await_args_list
        assert len(calls) == 2
        tool_result = next(message for message in calls[1].kwargs["messages"] if message["role"] == "tool")
        assert "Tool 'subagent' not found" in tool_result["content"]
        assert not loop.subagents.statuses_for_session(key)
    finally:
        chats.close()
        await loop.aclose()


async def test_transient_session_file_tools_keep_shared_memory_out_of_the_turn(tmp_path) -> None:
    loop = _loop(tmp_path, [], tools_config=ToolsConfig(restrict_to_workspace=True))
    memory = loop.context.memory
    memory.user_file.write_text("Profile contains Private Marker", encoding="utf-8")
    memory.wiki_dir.mkdir()
    (memory.wiki_dir / "project.md").write_text("Wiki contains Private Marker", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("Project contains Private Marker", encoding="utf-8")
    heartbeat = tmp_path / "HEARTBEAT.md"
    heartbeat.write_text("Existing scheduled checks", encoding="utf-8")
    key = "websocket:private-files"
    await loop.sessions.state.register_transient(key, disabled_tools={"cron"})
    try:
        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=[
            LLMResponse(content="", tool_calls=[
                ToolCallRequest(id="profile", name="read_file", arguments={"path": "USER.md"}),
                ToolCallRequest(id="skill", name="read_file", arguments={"path": "skills/memory/SKILL.md"}),
                ToolCallRequest(id="wiki", name="read_file", arguments={"path": "memory/wiki/project.md"}),
                ToolCallRequest(id="listing", name="list_dir", arguments={"path": ".", "recursive": True}),
                ToolCallRequest(id="read-heartbeat", name="read_file", arguments={"path": "HEARTBEAT.md"}),
                ToolCallRequest(id="edit-heartbeat", name="edit_file", arguments={
                    "path": "HEARTBEAT.md", "old_text": "Existing scheduled checks", "new_text": "New checks",
                }),
                ToolCallRequest(id="edit", name="edit_file", arguments={
                    "path": "USER.md", "old_text": "Private Marker", "new_text": "Remember this",
                }),
                ToolCallRequest(id="project", name="write_file", arguments={
                    "path": "result.txt", "content": "Project artifact",
                }),
            ]),
            LLMResponse(content="done"),
        ])
        await loop._process_message(_message(key, "Work with these files"))

        request = loop.provider.chat_stream_with_retry.await_args.kwargs["messages"]
        results = {row['tool_call_id']: row['content'] for row in request if row['role'] == 'tool'}
        for tool_call_id in ("profile", "wiki", "skill", "edit"):
            assert "This path is not available in this session" in results[tool_call_id]
        assert "notes.txt" in results["listing"]
        assert "USER.md" not in results["listing"]
        assert "project.md" not in results["listing"]
        assert memory.user_file.read_text(encoding="utf-8") == "Profile contains Private Marker"
        assert "Existing scheduled checks" in results["read-heartbeat"]
        assert "read-only to file tools in this session" in results["edit-heartbeat"]
        assert heartbeat.read_text(encoding="utf-8") == "Existing scheduled checks"
        assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "Project artifact"

        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=[
            LLMResponse(content="", tool_calls=[
                ToolCallRequest(id="read", name="read_file", arguments={"path": "memory/wiki/project.md"}),
                ToolCallRequest(id="read-heartbeat", name="read_file", arguments={"path": "HEARTBEAT.md"}),
            ]),
            LLMResponse(content="", tool_calls=[ToolCallRequest(id="edit-heartbeat", name="edit_file", arguments={
                "path": "HEARTBEAT.md", "old_text": "Existing scheduled checks", "new_text": "New checks",
            })]),
            LLMResponse(content="done"),
        ])
        await loop.process_direct("Read project memory and update scheduled checks", session_key="cli:ordinary")
        assert heartbeat.read_text(encoding="utf-8") == "New checks"
        request = loop.provider.chat_stream_with_retry.await_args.kwargs["messages"]
        assert any(row['role'] == 'tool' and "Wiki contains Private Marker" in row['content'] for row in request)
    finally:
        await loop.aclose()


@pytest.mark.parametrize("selection", ["explicit_empty", "disable_all", "default"])
async def test_turn_tool_selection_preserves_empty_registries(tmp_path, monkeypatch, selection) -> None:
    monkeypatch.setattr("nanobot.agent.tools.loader.entry_points", lambda **kwargs: [])
    loop = _loop(tmp_path, [], max_tool_iterations=2)
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
        await loop.sessions.state.get(key)
        await loop.sessions.state.set_policy(key, SessionPolicy(disabled_tools=frozenset(loop.tools.tool_names)))

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
        await loop.sessions.state.register_transient(key)
    else:
        await loop.sessions.state.get(key)
        await loop.sessions.state.set_policy(key, SessionPolicy(log_content=privacy != "quiet"))
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
    session = await loop.sessions.state.register_transient("websocket:cancel-private")
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
        await loop.sessions.state.register_transient(key)
    else:
        await loop.sessions.state.get(key)
    secret = "synthetic-private-worker-content"
    if failure == "runner":
        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=ValueError(secret))
    else:
        async def fail_after_discard(*args, **kwargs):
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
async def test_missing_required_session_cannot_fall_back_to_disk(tmp_path) -> None:
    loop = _loop(tmp_path, [])
    key = "websocket:transient-stale"
    await loop.sessions.state.register_transient(key)
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
        assert await loop.sessions.state.delete(key)
        assert loop.sessions.read_session_file(SubagentSessions.key(task_id)) is None
        await loop.sessions.state.get(key)

        assert loop.subagents.statuses_for_session(key) == {}
        await loop._enqueue_session_message(notice)
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
    await loop.sessions.state.register_transient(
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
    await asyncio.wait_for(loop._pending_queues.wait_for_controls(key), timeout=2)
    assert loop.sessions.get_cached(key) is None
    assert loop._file_state_store.for_session(key) is not previous_file_state
    terminate_exec_sessions.assert_awaited_once_with(key)

    loop.stop()
    await loop.bus.publish_inbound(_message(key, "wake"))
    await asyncio.wait_for(run_task, timeout=2)
