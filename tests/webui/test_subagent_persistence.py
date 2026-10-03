"""A restarted host replays task observations without recovering execution."""

import asyncio
import json
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.agent.memory import Consolidator
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentControlError, SubagentManager
from nanobot.agent.subagent_sessions import SUBAGENT, TASK_METADATA_KEY, SubagentSessions
from nanobot.agent.tools.context import RequestContext, current_request_context, request_context
from nanobot.agent.tools.session_messages import ListSessionsTool, SendSessionMessageTool
from nanobot.agent.tools.sessions import ReadSessionTool, SearchSessionsTool
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.providers.base import GenerationSettings, LLMProvider, ProviderConversationState
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import SessionHandleResolver
from nanobot.session.summary import SessionSummaryCheckpoint, is_summary_checkpoint
from nanobot.session.types import PARENT_SESSION_KEY, SESSION_TYPE_KEY
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.webui.gateway_services import build_gateway_services


def manager_with_storage(workspace, sessions_root):
    sessions = SessionManager(workspace, sessions_root=sessions_root)
    manager = SubagentManager(
        workspace=workspace, bus=MessageBus(), max_tool_result_chars=16000,
        consolidator=MagicMock(spec=Consolidator), session_manager=sessions,
    )
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128000)
    return manager, sessions, runtime


def gateway_for(manager, sessions, workspace):
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=manager.bus, session_manager=sessions,
        static_dist_path=None, workspace_path=workspace, default_restrict_to_workspace=True,
        config_path=workspace.parent / "config.json", runtime_model_name=None,
        runtime_surface="gateway", runtime_capabilities_overrides=None, subagent_manager=manager,
    )
    token = gateway.tokens.issue_api_token(60)
    return gateway, SimpleNamespace(remote_address=("127.0.0.1", 12345)), Headers({"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_abrupt_process_exit_preserves_terminal_records_and_interrupts_pending_work(tmp_path):
    workspace, sessions_root = tmp_path / "agent", tmp_path / "sessions"
    script = tmp_path / "host.py"
    result_path = tmp_path / "ids.json"
    script.write_text(textwrap.dedent('''
        import asyncio, json, os, sys
        from pathlib import Path
        from unittest.mock import AsyncMock, MagicMock
        from nanobot.agent.hook import AgentHookContext
        from nanobot.agent.memory import Consolidator
        from nanobot.agent.runner import AgentRunResult
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, LLMUsage
        from nanobot.session.manager import SessionManager
        from nanobot.utils.llm_runtime import LLMRuntime

        async def main():
            workspace = Path(sys.argv[1])
            sessions = SessionManager(workspace, sessions_root=Path(sys.argv[2]))
            parent = sessions.get_or_create("websocket:parent")
            parent.add_message("user", "Delegate the inspection", webui_turn_id="turn-1")
            sessions.save(parent, fsync=True)
            manager = SubagentManager(workspace=workspace, bus=MessageBus(), max_tool_result_chars=16000,
                max_concurrent_subagents=1, consolidator=MagicMock(spec=Consolidator), session_manager=sessions)
            provider = MagicMock(spec=LLMProvider)
            provider.generation = GenerationSettings()
            runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128000)
            manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Verified"))
            await manager.run_inline("completed", session_key=parent.key, origin_turn_id="turn-1", runtime=runtime)
            done, = manager.statuses_for_session(parent.key)
            entered = asyncio.Event()
            async def pending(spec):
                await spec.hook.after_iteration(AgentHookContext(iteration=1, messages=[], response=LLMResponse(content="Partial findings"), usage=LLMUsage.reported(input_tokens=10, output_tokens=5)))
                entered.set()
                await asyncio.Event().wait()
            manager.runner.run = pending
            await manager.spawn("running", session_key=parent.key, origin_turn_id="turn-1", runtime=runtime)
            await entered.wait()
            await manager.spawn("queued", session_key=parent.key, origin_turn_id="turn-1", runtime=runtime)
            statuses = manager.statuses_for_session(parent.key)
            ids = {status.task_description: task_id for task_id, status in statuses.items()}
            manager.send(ids["running"], parent.key, "Not yet delivered")
            Path(sys.argv[3]).write_text(json.dumps(ids))
            os._exit(0)
        asyncio.run(main())
    '''), encoding="utf-8")
    subprocess.run([sys.executable, str(script), str(workspace), str(sessions_root), str(result_path)], check=True, timeout=15)
    ids = json.loads(result_path.read_text())
    manager, sessions, _ = manager_with_storage(workspace, sessions_root)
    manager.runner.run = AsyncMock()
    assert manager.check(ids["running"], "websocket:parent").state == "running"
    manager.recover_interrupted()
    gateway, connection, headers = gateway_for(manager, sessions, workspace)
    path = f"/api/sessions/{quote('websocket:parent', safe='')}/subagents"
    try:
        first = await gateway.http.dispatch(connection, Request(path, headers))
        assert first.status_code == 200
        by_id = {task["task_id"]: task for task in json.loads(first.body)["tasks"]}
        assert by_id[ids["completed"]]["state"] == "done"
        assert by_id[ids["completed"]]["result"] == "Verified"
        for name in ("running", "queued"):
            assert by_id[ids[name]]["state"] == "interrupted"
            assert by_id[ids[name]]["stop_reason"] == "host_restarted"
        assert by_id[ids["running"]]["result"] == "Partial findings"
        assert by_id[ids["running"]]["partial"] is True
        assert by_id[ids["running"]]["usage"]["input_tokens"] == 10
        assert list(by_id[ids["running"]]["receipts"].values()) == ["undelivered"]
        assert by_id[ids["queued"]]["partial"] is False
        assert all(task["origin_turn_id"] == "turn-1" for task in by_id.values())
        assert all(task["created_at"] > 0 and task["completed_at"] > 0 for task in by_id.values())
        assert manager.get_running_count() == 0
        assert manager.bus.inbound_size == 0
        manager.runner.run.assert_not_called()
        second = await gateway.http.dispatch(connection, Request(path, headers))
        assert second.body == first.body
        persisted_parent = sessions.read_session_file("websocket:parent")
        assert [row["content"] for row in persisted_parent["messages"]] == ["Delegate the inspection"]
        assert {row["key"] for row in sessions.list_sessions()} == {
            "websocket:parent", *(SubagentSessions.key(task_id) for task_id in ids.values()),
        }
        assert [handle.session_key for handle in SessionHandleResolver(sessions).list_all()] == ["websocket:parent"]
        assert not list(sessions.sessions_dir.glob("*.subagents.json"))
        with pytest.raises(SubagentControlError, match="task unavailable"):
            manager.check(ids["completed"], "websocket:other")
        third_manager, _, _ = manager_with_storage(workspace, sessions_root)
        assert {key: value.as_dict() for key, value in third_manager.statuses_for_session("websocket:parent").items()} == by_id
        await third_manager.close()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_child_preserves_transcript_provider_state_and_summary_in_common_session(tmp_path):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    provider_state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test", version=1,
        payload={"response_id": "child-response"},
    )

    async def run(spec):
        request = current_request_context()
        assert request.session_key == spec.session_key
        assert spec.session_key.startswith("subagent:")
        assert spec.initial_messages[-1] == {"role": "user", "content": "Inspect the config"}
        assert {"subagent", "send_session_message", "list_sessions"}.isdisjoint(
            definition["function"]["name"] for definition in spec.tools.get_definitions()
        )
        return AgentRunResult(
            messages=[*spec.initial_messages,
                      {"role": "assistant", "content": "Inspecting", "tool_calls": [
                          {"id": "read-1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
                      ]},
                      {"role": "tool", "tool_call_id": "read-1", "content": "config contents"},
                      {"role": "assistant", "content": "Verified"}],
            final_content="Verified", provider_state=provider_state,
            summary_checkpoint=SessionSummaryCheckpoint("Configuration inspected", 4),
        )

    manager.runner.run = run
    try:
        await manager.run_inline("Inspect the config", session_key="websocket:parent", runtime=runtime)
        task_id, = manager.statuses_for_session("websocket:parent")
        reopened, restored, _ = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
        child = restored.get_existing(SubagentSessions.key(task_id))
        assert child.metadata[SESSION_TYPE_KEY] == SUBAGENT.name
        assert child.metadata[PARENT_SESSION_KEY] == "websocket:parent"
        assert [message["role"] for message in child.messages] == ["user", "assistant", "tool", "user", "assistant"]
        assert is_summary_checkpoint(child.messages[3])
        assert child.metadata["_last_summary"]["text"] == "Configuration inspected"
        assert child.provider_state == provider_state
        assert reopened.check(task_id, "websocket:parent").result == "Verified"
        await reopened.close()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_child_is_unavailable_to_public_session_tools(tmp_path):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    sessions.save(sessions.get_or_create("websocket:other"))
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Private findings"))
    try:
        await manager.run_inline("Private investigation", session_key="websocket:parent", runtime=runtime)
        task_id, = manager.statuses_for_session("websocket:parent")
        child_key = SubagentSessions.key(task_id)
        public_handle = SessionHandleResolver(sessions).handle_for_session("websocket:other")
        sender = SendSessionMessageTool(sessions=sessions, bus=manager.bus)
        with request_context(RequestContext(channel="websocket", chat_id="other", session_key="websocket:other")):
            assert json.loads(await SearchSessionsTool(sessions).execute(query="Private investigation"))["results"] == []
            assert "not found" in await ReadSessionTool(sessions).execute(session_key=child_key)
            handles = json.loads(await ListSessionsTool(sessions).execute())
            assert len(handles) == 1
            assert "Error:" in await sender.execute(to=child_key, content="bypass parent", expect_reply=False)
        with request_context(RequestContext(channel="websocket", chat_id="parent", session_key=child_key)):
            assert "Error:" in await sender.execute(to=public_handle.name, content="bypass parent", expect_reply=False)
        assert manager.bus.inbound_size == 0
        assert manager.check(task_id, "websocket:parent").result == "Private findings"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_constructing_another_reader_does_not_interrupt_running_work(tmp_path):
    workspace, root = tmp_path / "agent", tmp_path / "sessions"
    manager, sessions, runtime = manager_with_storage(workspace, root)
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(_spec):
        entered.set()
        await release.wait()
        return AgentRunResult(messages=[], final_content="Verified")

    manager.runner.run = held
    try:
        await manager.spawn("inspect", session_key="websocket:parent", runtime=runtime)
        await entered.wait()
        task_id, = manager.statuses_for_session("websocket:parent")
        receipt = manager.send(task_id, "websocket:parent", "Follow-up")
        path = sessions._get_session_path(SubagentSessions.key(task_id))
        before = path.read_bytes()
        reader, _, _ = manager_with_storage(workspace, root)
        observed = reader.check(task_id, "websocket:parent")
        assert observed.state == "running"
        assert observed.receipts[receipt["message_id"]] == "accepted"
        assert path.read_bytes() == before
        await reader.close()
        assert path.read_bytes() == before
    finally:
        release.set()
        await manager.close()


@pytest.mark.asyncio
async def test_webui_deletion_cancels_parent_work_and_removes_child_sessions(tmp_path):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    entered = asyncio.Event()

    async def held(_spec):
        entered.set()
        await asyncio.Event().wait()

    manager.runner.run = held
    await manager.spawn("inspect", session_key="websocket:parent", runtime=runtime)
    await entered.wait()
    task_id, = manager.statuses_for_session("websocket:parent")
    child_key = SubagentSessions.key(task_id)
    gateway, connection, _ = gateway_for(manager, sessions, tmp_path / "agent")

    async def discard(key):
        assert sessions.read_session_file(key) is not None
        await manager.cancel_by_session(key)

    gateway.http.discard_session = AsyncMock(side_effect=discard)
    try:
        response = await gateway.http.dispatch_webui_mutation(
            connection, "session.delete", {"key": "websocket:parent"},
        )
        assert response.status_code == 200
        assert json.loads(response.body)["deleted"] is True
        gateway.http.discard_session.assert_awaited_once_with("websocket:parent")
        assert sessions.read_session_file("websocket:parent") is None
        assert sessions.read_session_file(child_key) is None
        assert manager.bus.inbound_size == 0
        assert manager.get_running_count() == 0
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_history_outlives_the_runtime_cache_and_follows_parent_deletion(tmp_path):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    manager.MAX_TERMINAL = 1
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Verified"))
    try:
        for name in ("first", "second"):
            await manager.run_inline(name, session_key="websocket:parent", origin_turn_id="turn-1", runtime=runtime)
        tasks = manager.statuses_for_session("websocket:parent")
        assert len(tasks) == 2
        assert len(manager.runtime_statuses()) == 1
        assert len(manager.statuses_for_session("websocket:parent", include_history=False)) == 1
        first = next(status for status in tasks.values() if status.task_description == "first")
        assert manager.check(first.task_id, "websocket:parent").result == "Verified"
        fork = sessions.fork_session_before_user_index("websocket:parent", "websocket:fork", 0)
        assert TASK_METADATA_KEY not in fork.metadata
        assert sessions.child_session_keys(fork.key) == []
        child_paths = [sessions._get_session_path(SubagentSessions.key(task_id)) for task_id in tasks]
        assert all(path.exists() for path in child_paths)
        assert sessions.delete_session("websocket:parent")
        assert not any(path.exists() for path in child_paths)
        assert manager.statuses_for_session("websocket:parent") == {}
        with pytest.raises(SubagentControlError):
            manager.check(first.task_id, "websocket:parent")
        manager.sessions.save(first)
        assert sessions.read_session_file("websocket:parent") is None
        assert not any(path.exists() for path in child_paths)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_task_progress_does_not_rewrite_parent_history_or_invalidate_checkpoint(tmp_path):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    parent = sessions.get_or_create("websocket:parent")
    parent.add_message("user", "Inspect config", webui_turn_id="turn-1")
    sessions.save(parent)
    path = sessions._get_session_path(parent.key)
    before, stamp = path.read_bytes(), path.stat()
    parent.metadata["runtime_checkpoint"] = {"phase": "tools_completed"}
    parent.provider_state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test", version=1,
        payload={"response_id": "private-response"},
    )
    sessions.save_runtime_checkpoint(parent)
    checkpoint_path = sessions._get_runtime_checkpoint_path(parent.key)
    checkpoint = checkpoint_path.read_bytes()
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Verified"))
    try:
        await manager.run_inline("check", session_key=parent.key, runtime=runtime)
        assert path.read_bytes() == before
        assert path.stat().st_ino == stamp.st_ino
        assert path.stat().st_mtime_ns == stamp.st_mtime_ns
        assert checkpoint_path.read_bytes() == checkpoint
        restored = SessionManager(tmp_path / "agent", sessions_root=tmp_path / "sessions").get_or_create(parent.key)
        assert restored.metadata["runtime_checkpoint"]["phase"] == "tools_completed"
        assert restored.provider_state.payload == {"response_id": "private-response"}
        assert len(manager.statuses_for_session(parent.key)) == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_temporary_parent_never_persists_task_content(tmp_path):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    parent = sessions.get_or_create_transient("websocket:temporary")
    async def run(_spec):
        assert current_request_context().log_content is False
        return AgentRunResult(messages=[], final_content="Private findings")

    manager.runner.run = run
    try:
        await manager.run_inline("private task", session_key=parent.key, runtime=runtime)
        assert len(manager.statuses_for_session(parent.key)) == 1
        assert sessions.read_session_file(parent.key) is None
        task_id, = manager.statuses_for_session(parent.key)
        child = sessions.get_cached(SubagentSessions.key(task_id))
        assert child is not None and not child.policy.persist
        assert sessions.read_session_file(child.key) is None
        reopened, _, _ = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
        assert reopened.statuses_for_session(parent.key) == {}
        await reopened.close()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_child_sessions_use_common_restore_and_migration(tmp_path):
    workspace, root = tmp_path / "agent", tmp_path / "sessions"
    manager, sessions, runtime = manager_with_storage(workspace, root)
    parent = sessions.get_or_create("websocket:parent")
    parent.add_message("user", "Inspect config")
    sessions.save(parent)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Verified"))
    try:
        await manager.run_inline("inspect", session_key=parent.key, runtime=runtime)
        task_id, = manager.statuses_for_session(parent.key)
        child_key = SubagentSessions.key(task_id)
        paths = [sessions._get_session_path(key) for key in (parent.key, child_key)]
        result = sessions.restore_sessions_to_workspace()
        assert result.restored == 2 and result.conflicts == ()
        for path in paths:
            assert (workspace / "sessions" / path.name).read_bytes() == path.read_bytes()
            path.unlink()
        reopened, migrated, _ = manager_with_storage(workspace, root)
        assert migrated.child_session_keys(parent.key) == [child_key]
        assert reopened.check(task_id, parent.key).result == "Verified"
        assert not list((workspace / "sessions").glob("*.jsonl"))
        await reopened.close()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_unreadable_task_history_is_not_an_empty_list(tmp_path):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    parent = sessions.get_or_create("websocket:parent")
    sessions.save(parent)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Verified"))
    await manager.run_inline("inspect", session_key=parent.key, runtime=runtime)
    task_id, = manager.statuses_for_session(parent.key)
    child = sessions.get_existing(SubagentSessions.key(task_id))
    child.metadata[TASK_METADATA_KEY] = "damaged"
    sessions.save(child)
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    try:
        path = f"/api/sessions/{quote(parent.key, safe='')}/subagents"
        response = await gateway.http.dispatch(connection, Request(path, headers))
        assert response.status_code == 503
        assert "task history unavailable" in response.body.decode()
    finally:
        await manager.close()
