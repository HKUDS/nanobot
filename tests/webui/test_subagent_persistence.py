"""A restarted host replays task observations without recovering execution."""

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
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.providers.base import GenerationSettings, LLMProvider, ProviderConversationState
from nanobot.session.manager import SessionManager
from nanobot.session.subagent_records import SUBAGENT_RECORDS_KEY
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
            Path(sys.argv[3]).write_text(json.dumps(ids))
            os._exit(0)
        asyncio.run(main())
    '''), encoding="utf-8")
    subprocess.run([sys.executable, str(script), str(workspace), str(sessions_root), str(result_path)], check=True, timeout=15)
    ids = json.loads(result_path.read_text())
    manager, sessions, _ = manager_with_storage(workspace, sessions_root)
    manager.runner.run = AsyncMock()
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
        assert [row["key"] for row in sessions.list_sessions()] == ["websocket:parent"]
        with pytest.raises(SubagentControlError, match="task unavailable"):
            manager.check(ids["completed"], "websocket:other")
        third_manager, _, _ = manager_with_storage(workspace, sessions_root)
        assert {key: value.as_dict() for key, value in third_manager.statuses_for_session("websocket:parent").items()} == by_id
        await third_manager.close()
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
        assert SUBAGENT_RECORDS_KEY not in fork.metadata
        assert sessions.read_subagent_records("websocket:fork") is None
        records_path = sessions._get_session_path("websocket:parent").with_suffix(".subagents.json")
        assert records_path.exists()
        assert sessions.delete_session("websocket:parent")
        assert not records_path.exists()
        assert manager.statuses_for_session("websocket:parent") == {}
        with pytest.raises(SubagentControlError):
            manager.check(first.task_id, "websocket:parent")
        manager.records.save(first)
        assert sessions.read_session_file("websocket:parent") is None
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
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Private findings"))
    try:
        await manager.run_inline("private task", session_key=parent.key, runtime=runtime)
        assert len(manager.statuses_for_session(parent.key)) == 1
        assert sessions.read_session_file(parent.key) is None
        assert sessions.read_subagent_records(parent.key) is None
        reopened, _, _ = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
        assert reopened.statuses_for_session(parent.key) == {}
        await reopened.close()
    finally:
        await manager.close()


def test_restore_and_migration_preserve_task_records_and_report_conflicts(tmp_path):
    workspace, root = tmp_path / "agent", tmp_path / "sessions"
    sessions = SessionManager(workspace, sessions_root=root)
    parent = sessions.get_or_create("websocket:parent")
    parent.add_message("user", "Inspect config")
    sessions.save(parent)
    records = {"version": 1, "tasks": []}
    sessions.save_subagent_records(parent.key, records)
    path = sessions._get_session_path(parent.key)
    record_path = path.with_suffix(".subagents.json")
    result = sessions.restore_sessions_to_workspace()
    assert result.restored == 1 and result.conflicts == ()
    legacy_path = workspace / "sessions" / path.name
    legacy_records = legacy_path.with_suffix(".subagents.json")
    assert legacy_records.read_bytes() == record_path.read_bytes()
    # Restoring must preserve a divergent workspace copy for manual resolution.
    legacy_records.write_text('{"version":1,"tasks":[{}]}', encoding="utf-8")
    assert sessions.restore_sessions_to_workspace().conflicts == (legacy_records,)
    SessionManager(workspace, sessions_root=root)
    assert legacy_path.exists() and legacy_records.exists()
    assert sessions.read_subagent_records(parent.key) == records
    legacy_records.write_bytes(record_path.read_bytes())
    path.unlink()
    record_path.unlink()
    reopened = SessionManager(workspace, sessions_root=root)
    assert reopened.read_subagent_records(parent.key) == records
    assert not legacy_path.exists() and not legacy_records.exists()


@pytest.mark.asyncio
async def test_unreadable_task_history_is_not_an_empty_list(tmp_path):
    manager, sessions, _ = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    parent = sessions.get_or_create("websocket:parent")
    sessions.save(parent)
    sessions.save_subagent_records(parent.key, {"version": 1, "tasks": "damaged"})
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    try:
        path = f"/api/sessions/{quote(parent.key, safe='')}/subagents"
        response = await gateway.http.dispatch(connection, Request(path, headers))
        assert response.status_code == 503
        assert "task history unavailable" in response.body.decode()
    finally:
        await manager.close()
