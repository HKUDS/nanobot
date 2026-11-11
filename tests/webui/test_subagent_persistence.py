import asyncio
import hashlib
import json
import subprocess
import sys
import textwrap
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote, urlencode

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.agent.memory import Consolidator
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentControlError, SubagentManager
from nanobot.agent.subagent_sessions import SUBAGENT, TASK_METADATA_KEY, SubagentSessions
from nanobot.agent.tools.context import RequestContext, current_request_context, request_context
from nanobot.agent.tools.session_messages import SendSessionMessageTool
from nanobot.agent.tools.sessions import ReadSessionTool, SearchSessionsTool
from nanobot.agent.tools.subagent import SubagentTool
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import SubagentTaskChanged
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ProviderConversationState,
    ToolCallRequest,
)
from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.jsonl_migration import WORKSPACE_BACKUP_DIR
from nanobot.session.location import SessionLocation
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import SessionHandleResolver
from nanobot.session.summary import SessionSummaryCheckpoint, is_summary_checkpoint
from nanobot.session.types import PARENT_SESSION_KEY, SESSION_TYPE_KEY
from nanobot.session.webui_turns import WebuiTurnCoordinator
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


async def wait_for_model_requests(manager, task_id, requests, count):
    task = manager._running_tasks[task_id]
    for _ in range(count):
        request = asyncio.create_task(requests.get())
        try:
            done, _ = await asyncio.wait(
                (request, task), timeout=5, return_when=asyncio.FIRST_COMPLETED,
            )
            if task in done:
                result = task.result()
                status = manager.check(task_id, "websocket:parent")
                pytest.fail(
                    "subagent ended before its activity was ready: "
                    f"state={status.state}, error={status.error!r}, result={result!r}"
                )
            assert request in done, "subagent made no progress to its next model request"
        finally:
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("wait", [False, True])
async def test_cancelled_task_creation_removes_committed_child(tmp_path, monkeypatch, wait):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    owner = "websocket:parent"
    await sessions.state.get(owner)
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    save = sessions._store.save
    children = []

    def blocked_save(session, **kwargs):
        save(session, **kwargs)
        if session.key.startswith("subagent:"):
            children.append(session.key)
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5), "test did not release child persistence"

    monkeypatch.setattr(sessions._store, "save", blocked_save)
    manager.runner.run = AsyncMock()

    async def create():
        with request_context(RequestContext(
            channel="websocket", chat_id="parent", session_key=owner,
            runtime=runtime, can_receive_background_results=True,
        )):
            return await SubagentTool(manager).execute(action="create", task="Inspect config", wait=wait)

    task = asyncio.create_task(create())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert len(children) == 1
        assert await sessions.state.read(children[0]) is None
        assert sessions.child_session_keys(owner) == []
        assert manager.statuses_for_session(owner) == {}
        assert manager.get_running_count() == 0
        manager.runner.run.assert_not_awaited()
        assert await sessions.state.read(owner) is not None
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await manager.close()
        await sessions.state.aclose()


@pytest.mark.asyncio
async def test_child_thread_reads_real_session_through_parent_without_new_persistence(tmp_path):
    workspace, root = tmp_path / "agent", tmp_path / "sessions"
    workspace.mkdir()
    (workspace / "config.txt").write_text("configured value", encoding="utf-8")
    manager, sessions, runtime = manager_with_storage(workspace, root)
    model_requests, release = asyncio.Queue(), asyncio.Event()
    final_text = ("## Findings\n\n" + "Verified configuration.\n" * 1000).rstrip()
    calls = 0

    async def respond(**_kwargs):
        nonlocal calls
        calls += 1
        model_requests.put_nowait(None)
        if calls == 1:
            return LLMResponse(content="Inspecting configuration", tool_calls=[
                ToolCallRequest("read-config", "read_file", {"path": "config.txt"}),
            ])
        await release.wait()
        return LLMResponse(content=final_text)

    runtime.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    gateway, connection, headers = gateway_for(manager, sessions, workspace)
    try:
        await manager.spawn("Inspect configuration", session_key="websocket:parent", runtime=runtime)
        task_id, = manager.statuses_for_session("websocket:parent")
        # Bound each round, rather than the combined startup/tool/persistence work.
        await wait_for_model_requests(manager, task_id, model_requests, 2)
        child_key = SubagentSessions.key(task_id)
        path = f"/api/sessions/websocket%3Aparent/subagents/{task_id}/webui-thread"
        files_before = set(root.rglob("*"))
        denied = await gateway.http.dispatch(connection, Request(path, Headers()))
        assert denied.status_code == 401
        unknown = []
        for candidate in (path.replace("parent", "other"), path.replace(task_id, "missing")):
            response = await gateway.http.dispatch(connection, Request(candidate, headers))
            assert response.status_code == 404
            unknown.append(response.body)
        assert unknown[0] == unknown[1]
        direct = await gateway.http.dispatch(connection, Request(
            f"/api/sessions/{quote(child_key, safe='')}/webui-thread", headers,
        ))
        assert direct.status_code == 404
        response = await gateway.http.dispatch(connection, Request(path, headers))
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        running = json.loads(response.body)
        assert running["active_turn_id"]
        assert [(event["event"], event.get("text")) for event in running["events"][:2]] == [
            ("user_message", "Inspect configuration"), ("message", "Inspecting configuration"),
        ]
        tool = next(event for event in running["events"] if event.get("kind") == "tool_hint")
        assert tool["tool_events"][0]["phase"] == "end"
        assert "configured value" in tool["tool_events"][0]["result"]
        assert set(root.rglob("*")) == files_before
        release.set()
        await asyncio.gather(*list(manager._running_tasks.values()))
        assert len(manager.check(task_id, "websocket:parent").result) == 16000
        await manager.close()
        manager, sessions, _ = manager_with_storage(workspace, root)
        gateway, connection, headers = gateway_for(manager, sessions, workspace)
        response = await gateway.http.dispatch(connection, Request(path, headers))
        completed = json.loads(response.body)
        assert completed["active_turn_id"] is None
        assert next(event["text"] for event in completed["events"] if event.get("turn_phase") == "answer") == final_text
        assert [event["projection_id"] for event in completed["events"][:3]] == [
            event["projection_id"] for event in running["events"]
        ]
        assert manager.get_running_count() == 0
        deleted = await gateway.http.dispatch_webui_mutation(connection, "session.delete", {"key": "websocket:parent"})
        assert deleted.status_code == 200
        assert (await gateway.http.dispatch(connection, Request(path, headers))).status_code == 404
    finally:
        release.set()
        await manager.close()


@pytest.mark.asyncio
async def test_new_unsaved_parent_has_an_empty_task_collection(tmp_path):
    workspace = tmp_path / "agent"
    manager, sessions, _ = manager_with_storage(workspace, tmp_path / "sessions")
    gateway, connection, headers = gateway_for(manager, sessions, workspace)
    key = "websocket:new-chat"
    try:
        response = await gateway.http.dispatch(
            connection, Request(f"/api/sessions/{quote(key, safe='')}/subagents", headers),
        )
        assert response.status_code == 200
        assert json.loads(response.body) == {"tasks": []}
        assert response.headers["Cache-Control"] == "no-store"
        assert sessions.read_session_metadata(key) is None
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_child_activity_replays_real_tool_errors_and_file_diffs(tmp_path):
    workspace, root = tmp_path / "agent", tmp_path / "sessions"
    workspace.mkdir()
    (workspace / "example.txt").write_text("before\n", encoding="utf-8")
    manager, sessions, runtime = manager_with_storage(workspace, root)
    model_requests = asyncio.Queue()
    release = asyncio.Event()
    responses = iter([
        LLMResponse(content="Read the file", tool_calls=[
            ToolCallRequest("read", "read_file", {"path": "example.txt"}),
        ]),
        LLMResponse(content="Edit the file", tool_calls=[
            ToolCallRequest("edit", "edit_file", {
                "path": "example.txt", "old_text": "before", "new_text": "after",
            }),
        ]),
        LLMResponse(content="Check the missing file", tool_calls=[
            ToolCallRequest("missing", "read_file", {"path": "missing.txt"}),
        ]),
    ])

    async def respond(**kwargs):
        for message in kwargs["messages"]:
            assert not ({"tool_events", "file_edit_events"} & message.keys())
        response = next(responses, None)
        model_requests.put_nowait(None)
        if response is not None:
            return response
        await release.wait()
        return LLMResponse(content="Edited the file; the other file does not exist.")

    runtime.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    gateway, connection, headers = gateway_for(manager, sessions, workspace)
    try:
        await manager.spawn("Edit and inspect files", session_key="websocket:parent", runtime=runtime)
        task_id, = manager.statuses_for_session("websocket:parent")
        await wait_for_model_requests(manager, task_id, model_requests, 4)
        path = f"/api/sessions/websocket%3Aparent/subagents/{task_id}/webui-thread"

        async def assert_activity(gateway, connection, headers):
            before = {file.name: file.read_bytes() for file in root.glob("*.jsonl")}
            response = await gateway.http.dispatch(connection, Request(path, headers))
            assert response.status_code == 200
            thread = json.loads(response.body)
            tools = [tool for event in thread["events"] for tool in event.get("tool_events", [])]
            failure = next(tool for tool in tools if tool["call_id"] == "missing" and tool["phase"] == "error")
            assert "File not found" in failure["error"]
            edits = [edit for event in thread["events"] if event["event"] == "file_edit" for edit in event["edits"]]
            completed = next(edit for edit in edits if edit["phase"] == "end")
            assert completed["added"] == completed["deleted"] == 1
            assert "+after" in completed["diff"]["text"]
            assert "-before" in completed["diff"]["text"]
            assert (workspace / "example.txt").read_text(encoding="utf-8") == "after\n"
            assert {file.name: file.read_bytes() for file in root.glob("*.jsonl")} == before
            return thread

        assert (await assert_activity(gateway, connection, headers))["active_turn_id"]
        release.set()
        await asyncio.gather(*list(manager._running_tasks.values()))
        await manager.close()
        manager, sessions, _ = manager_with_storage(workspace, root)
        gateway, connection, headers = gateway_for(manager, sessions, workspace)
        assert (await assert_activity(gateway, connection, headers))["active_turn_id"] is None
        assert manager.check(task_id, "websocket:parent").state == "done"
    finally:
        release.set()
        await manager.close()


@pytest.mark.asyncio
async def test_provider_hosted_activity_is_visible_before_response_and_replays_in_order(tmp_path):
    workspace, root = tmp_path / "agent", tmp_path / "sessions"
    workspace.mkdir()
    manager, sessions, runtime = manager_with_storage(workspace, root)
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(*, on_tool_call_delta, messages, **_kwargs):
        assert all(not ({"tool_events", "file_edit_events"} & message.keys()) for message in messages)
        activity = {
            "kind": "hosted_tool", "call_id": "hosted-search", "name": "web_search",
            "arguments": {"query": "nanobot"},
        }
        await on_tool_call_delta({**activity, "phase": "start"})
        entered.set()
        await release.wait()
        await on_tool_call_delta({**activity, "phase": "end", "result": "Found documentation"})
        return LLMResponse(content="## Findings\n\nFound documentation.")

    runtime.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    gateway, connection, headers = gateway_for(manager, sessions, workspace)
    try:
        await manager.spawn("Search documentation", session_key="websocket:parent", runtime=runtime)
        await asyncio.wait_for(entered.wait(), 5)
        task_id, = manager.statuses_for_session("websocket:parent")
        path = f"/api/sessions/websocket%3Aparent/subagents/{task_id}/webui-thread"
        response = await gateway.http.dispatch(connection, Request(path, headers))
        running = json.loads(response.body)
        tool = next(event for event in running["events"] if event.get("kind") == "tool_hint")
        assert tool["tool_events"][0]["phase"] == "start"
        assert running["active_turn_id"]
        _, child = manager.read_session(task_id, "websocket:parent")
        assert child.get_history() == [{"role": "user", "content": "Search documentation"}]

        release.set()
        await asyncio.gather(*list(manager._running_tasks.values()))
        await manager.close()
        manager, sessions, _ = manager_with_storage(workspace, root)
        gateway, connection, headers = gateway_for(manager, sessions, workspace)
        response = await gateway.http.dispatch(connection, Request(path, headers))
        completed = json.loads(response.body)
        assert completed["active_turn_id"] is None
        activity_index = next(i for i, event in enumerate(completed["events"]) if event.get("kind") == "tool_hint")
        answer_index = next(i for i, event in enumerate(completed["events"]) if event.get("turn_phase") == "answer")
        assert activity_index < answer_index
        tool = completed["events"][activity_index]["tool_events"][0]
        assert tool["phase"] == "end"
        assert tool["result"] == "Found documentation"
        _, child = manager.read_session(task_id, "websocket:parent")
        assert all(not ({"tool_events", "file_edit_events"} & message.keys()) for message in child.get_history())
    finally:
        release.set()
        await manager.close()


@pytest.mark.asyncio
async def test_sidebar_listing_and_handle_allocation_do_not_decode_child_tasks(tmp_path, monkeypatch):
    import nanobot.session.sqlite_store as sqlite_store

    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    owner = "websocket:parent"
    await sessions.state.get(owner)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Private findings"))
    try:
        await manager.run_inline("Earlier task", session_key=owner, origin_turn_id="old-turn", runtime=runtime)
        gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
        original = sqlite_store._object

        def checked_object(raw):
            assert '"subagent_task"' not in raw, "sidebar decoded a child task"
            return original(raw)

        monkeypatch.setattr(sqlite_store, "_object", checked_object)
        response = await gateway.http.dispatch(connection, Request("/api/sessions", headers))
        assert response.status_code == 200
        rows = json.loads(response.body)["sessions"]
        assert [row["key"] for row in rows] == [owner]
        assert rows[0]["handle"]["name"]
        response = await gateway.http.dispatch(connection, Request("/api/sessions", headers))
        assert response.status_code == 200
    finally:
        await manager.close()
        await sessions.state.aclose()


@pytest.mark.asyncio
async def test_task_changes_use_parent_chat_events_and_saved_child_observations(tmp_path):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    gateway, _, _ = gateway_for(manager, sessions, tmp_path / "agent")
    channel = WebSocketChannel(WebSocketConfig(), manager.bus, gateway=gateway)
    channel._safe_send_to = AsyncMock()
    parent_connection, other_connection = MagicMock(), MagicMock()
    channel._attach(parent_connection, "parent")
    channel._attach(other_connection, "other")
    coordinator = WebuiTurnCoordinator(manager.bus, sessions, schedule_background=MagicMock())
    entered, release = asyncio.Queue(), asyncio.Event()

    async def held(spec):
        await spec.checkpoint_callback({"phase": "awaiting_model", "iteration": 1})
        await entered.put(True)
        await release.wait()
        return AgentRunResult(messages=[], final_content="## Private findings\n\n- Verified")

    async def deliver():
        await manager.bus.drain()
        while manager.bus.outbound_size:
            message = await manager.bus.consume_outbound()
            assert isinstance(message.event, SubagentTaskChanged)
            await channel.send(message)
        return [
            (call.args[0], json.loads(call.args[1]))
            for call in channel._safe_send_to.await_args_list
        ]

    manager.runner.run = held
    try:
        with coordinator.connected():
            for chat in ("parent", "parent", "other"):
                await manager.spawn(
                    "Investigate configuration", origin_channel="websocket", origin_chat_id=chat,
                    session_key=f"websocket:{chat}", origin_turn_id="finished-parent-turn", runtime=runtime,
                )
                # The checkpoint uses real storage; this checks routing, not disk latency.
                await asyncio.wait_for(entered.get(), 30)
            first, sibling = manager.statuses_for_session("websocket:parent")
            foreign, = manager.statuses_for_session("websocket:other")
            parent = await sessions.state.read("websocket:parent")
            parent.add_message("assistant", "Parent reply already delivered")
            await sessions.state.finish_turn(parent)
            original_messages = parent.messages.copy()
            routed = await deliver()
            assert {payload["task"]["task_id"] for conn, payload in routed if conn is parent_connection} == {first, sibling}
            assert {payload["task"]["task_id"] for conn, payload in routed if conn is other_connection} == {foreign}
            for _, payload in routed:
                assert payload["event"] == "subagent_task"
                assert "turn_id" not in payload
                assert "owner" not in payload["task"]
                assert payload["task"]["phase"] == "awaiting_model"
                assert payload["task"]["revision"] > 1
            previous_revision = manager.check(first, "websocket:parent").revision
            channel._safe_send_to.reset_mock()
            stopped = await manager.cancel(first, "websocket:parent")
            routed = await deliver()
            assert routed and all(conn is parent_connection for conn, _ in routed)
            assert all(payload["event"] == "subagent_task_settled" and payload["state"] == "cancelled"
                       for _, payload in routed)
            assert all(set(payload) == {"event", "chat_id", "task_id", "state", "revision", "completed_at"}
                       for _, payload in routed)
            assert stopped.revision > previous_revision
            assert manager.check(sibling, "websocket:parent").state == "running"
            channel._safe_send_to.reset_mock()
            release.set()
            await asyncio.gather(*list(manager._running_tasks.values()), return_exceptions=True)
            routed = await deliver()
            assert any(conn is parent_connection and payload["event"] == "subagent_task_settled"
                       and payload["state"] == "done" for conn, payload in routed)
            assert all("Private findings" not in json.dumps(payload) for _, payload in routed)
            assert parent.messages == original_messages
            saved = manager.sessions.status(sibling, "websocket:parent")
            assert saved.revision == manager.check(sibling, "websocket:parent").revision
            assert saved.result == "## Private findings\n\n- Verified"

            channel._safe_send_to.reset_mock()
            await manager.spawn(
                "Queued before parent deletion", origin_channel="websocket", origin_chat_id="parent",
                session_key="websocket:parent", runtime=runtime,
            )
            await manager.bus.drain()
            assert manager.bus.outbound_size > 0
            await sessions.state.delete("websocket:parent")
            assert await deliver() == []
    finally:
        await manager.close()
        await manager.bus.drain()
        await channel._cleanup_connection(parent_connection)
        await channel._cleanup_connection(other_connection)


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
            sessions.save(parent)
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
            await manager.send(ids["running"], parent.key, "Not yet delivered")
            Path(sys.argv[3]).write_text(json.dumps(ids))
            os._exit(0)
        asyncio.run(main())
    '''), encoding="utf-8")
    subprocess.run([sys.executable, str(script), str(workspace), str(sessions_root), str(result_path)], check=True, timeout=15)
    ids = json.loads(result_path.read_text())
    manager, sessions, _ = manager_with_storage(workspace, sessions_root)
    manager.runner.run = AsyncMock()
    assert manager.check(ids["running"], "websocket:parent").state == "running"
    await manager.recover_interrupted()
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
        assert [handle.session_key for handle in await SessionHandleResolver(sessions).alist_all()] == ["websocket:parent"]
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
        assert {"subagent", "send_session_message"}.isdisjoint(
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
        public_handle = await SessionHandleResolver(sessions).ahandle_for_session("websocket:other")
        sender = SendSessionMessageTool(sessions=sessions, bus=manager.bus)
        with request_context(RequestContext(channel="websocket", chat_id="other", session_key="websocket:other")):
            assert json.loads(await SearchSessionsTool(sessions).execute(query="Private investigation"))["results"] == []
            assert "not found" in await ReadSessionTool(sessions).execute(session_key=child_key)
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
        receipt = await manager.send(task_id, "websocket:parent", "Follow-up")
        child_key = SubagentSessions.key(task_id)
        before = sessions.read_session_file(child_key)
        reader, _, _ = manager_with_storage(workspace, root)
        observed = reader.check(task_id, "websocket:parent")
        assert observed.state == "running"
        assert observed.receipts[receipt["message_id"]] == "accepted"
        assert sessions.read_session_file(child_key) == before
        await reader.close()
        assert sessions.read_session_file(child_key) == before
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
        fork = await sessions.state.fork("websocket:parent", "websocket:fork", 0)
        assert TASK_METADATA_KEY not in fork.metadata
        assert sessions.child_session_keys(fork.key) == []
        child_keys = [SubagentSessions.key(task_id) for task_id in tasks]
        assert all(sessions.read_session_file(key) is not None for key in child_keys)
        assert await sessions.state.delete("websocket:parent")
        assert all(sessions.read_session_file(key) is None for key in child_keys)
        assert manager.statuses_for_session("websocket:parent") == {}
        with pytest.raises(SubagentControlError):
            manager.check(first.task_id, "websocket:parent")
        assert not await manager.sessions.save(first)
        assert sessions.read_session_file("websocket:parent") is None
        assert all(sessions.read_session_file(key) is None for key in child_keys)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_task_progress_does_not_rewrite_parent_history_or_invalidate_checkpoint(tmp_path):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    parent = sessions.get_or_create("websocket:parent")
    parent.add_message("user", "Inspect config", webui_turn_id="turn-1")
    sessions.save(parent)
    parent = await sessions.state.read(parent.key)
    parent.provider_state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test", version=1,
        payload={"response_id": "private-response"},
    )
    await sessions.state.checkpoint_view(parent, {"phase": "tools_completed"})
    before = sessions.read_session_file(parent.key)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Verified"))
    try:
        await manager.run_inline("check", session_key=parent.key, runtime=runtime)
        assert sessions.read_session_file(parent.key) == before
        restored = SessionManager(tmp_path / "agent", sessions_root=tmp_path / "sessions").get_or_create(parent.key)
        assert restored.metadata["runtime_checkpoint"]["phase"] == "tools_completed"
        assert restored.provider_state.payload == {"response_id": "private-response"}
        assert len(manager.statuses_for_session(parent.key)) == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_task_control_and_panel_do_not_read_parent_or_child_history(tmp_path, monkeypatch):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    parent = sessions.get_or_create("websocket:parent")
    parent.add_message("user", "Inspect configuration.")
    sessions.save(parent)
    await sessions.state.read(parent.key)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Verified"))
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    try:
        assert await manager.run_inline("check", session_key=parent.key, runtime=runtime) == "Verified"
        status, = manager.statuses_for_session(parent.key).values()

        def history_unavailable(*_args, **_kwargs):
            pytest.fail("task ownership and status reads must not request conversation history")

        def all_sessions_unavailable(*_args, **_kwargs):
            pytest.fail("task panels must query their own child metadata directly")

        monkeypatch.setattr(sessions, "get_cached", history_unavailable)
        monkeypatch.setattr(sessions._store, "list_metadata", all_sessions_unavailable)
        assert manager.sessions.exists(parent.key)
        assert manager.sessions.contains(status.task_id, parent.key)
        assert not manager.sessions.contains(status.task_id, "websocket:other")
        metadata = sessions.get_cached_metadata(SubagentSessions.key(status.task_id))
        assert metadata[TASK_METADATA_KEY]["state"] == "done"
        assert metadata[TASK_METADATA_KEY]["revision"] == status.revision
        assert manager.check(status.task_id, parent.key).result == "Verified"
        response = await gateway.http.dispatch(
            connection, Request("/api/sessions/websocket%3Aparent/subagents", headers),
        )
        assert response.status_code == 200
        assert [task["task_id"] for task in json.loads(response.body)["tasks"]] == [status.task_id]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_task_panel_reads_storage_off_loop_and_keeps_newer_completion(tmp_path, monkeypatch):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    runner_entered, finish_task = asyncio.Event(), asyncio.Event()
    history_entered = asyncio.Event()
    release_history = threading.Event()
    loop = asyncio.get_running_loop()
    owner_thread = threading.get_ident()
    original_load = manager.sessions.load
    request_task = None

    async def run(_spec):
        runner_entered.set()
        await finish_task.wait()
        return AgentRunResult(messages=[], final_content="Verified")

    def paused_history(owner):
        assert threading.get_ident() != owner_thread, "task panel storage reads must leave the event loop"
        loop.call_soon_threadsafe(history_entered.set)
        assert release_history.wait(5), "task panel history read was not released"
        return original_load(owner)

    manager.runner.run = run
    try:
        await manager.spawn("check", session_key="websocket:parent", runtime=runtime)
        await asyncio.wait_for(runner_entered.wait(), 5)
        task_id, = manager.statuses_for_session("websocket:parent")
        previous_revision = manager.check(task_id, "websocket:parent").revision
        execution = manager._running_tasks[task_id]
        monkeypatch.setattr(manager.sessions, "load", paused_history)
        request_task = asyncio.create_task(gateway.http.dispatch(
            connection, Request("/api/sessions/websocket%3Aparent/subagents", headers),
        ))
        await asyncio.wait_for(history_entered.wait(), 5)
        finish_task.set()
        await asyncio.wait_for(execution, 5)
        release_history.set()

        response = await asyncio.wait_for(request_task, 5)
        assert response.status_code == 200
        task, = json.loads(response.body)["tasks"]
        assert task["task_id"] == task_id and task["state"] == "done"
        assert task["revision"] > previous_revision
    finally:
        release_history.set()
        finish_task.set()
        if request_task is not None:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        await manager.close()


@pytest.mark.asyncio
async def test_temporary_parent_never_persists_task_content(tmp_path, monkeypatch):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    parent = await sessions.state.register_transient("websocket:temporary")
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

        def history_unavailable(*_args, **_kwargs):
            pytest.fail("temporary task control must not request conversation history")

        monkeypatch.setattr(sessions, "get_cached", history_unavailable)
        assert sessions.get_cached_metadata(child.key)[TASK_METADATA_KEY]["state"] == "done"
        assert manager.check(task_id, parent.key).result == "Private findings"
        assert len(manager.statuses_for_session(parent.key)) == 1
        gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
        path = "/api/sessions/websocket%3Atemporary/subagents"
        empty = await gateway.http.dispatch(connection, Request(path + "?scope=page", headers))
        selected = await gateway.http.dispatch(connection, Request(path + f"?scope=page&task_id={task_id}", headers))
        assert json.loads(empty.body)["tasks"] == []
        assert [task["task_id"] for task in json.loads(selected.body)["tasks"]] == [task_id]
        reopened, _, _ = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
        assert reopened.statuses_for_session(parent.key) == {}
        await reopened.close()
        await sessions.state.delete(parent.key)
        deleted = await gateway.http.dispatch(connection, Request(path + f"?scope=page&task_id={task_id}", headers))
        assert json.loads(deleted.body)["tasks"] == []
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_child_sessions_migrate_from_legacy_jsonl_and_reopen(tmp_path):
    workspace, root = tmp_path / "agent", tmp_path / "sessions"
    parent_key, task_id = "websocket:parent", "legacy-inspection"
    child_key = SubagentSessions.key(task_id)
    task_metadata = {
        "task_id": task_id, "owner": parent_key, "revision": 3,
        "label": "inspect", "task_description": "inspect", "state": "done", "phase": "done",
        "created_at": 1767225600.0, "completed_at": 1767225601.2, "elapsed_seconds": 1.2,
        "origin_turn_id": "turn-1", "iteration": 1, "result": "Verified", "stop_reason": "stop",
    }
    fixtures = {
        parent_key: [
            {"_type": "metadata", "key": parent_key, "metadata": {"webui": True},
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
             "last_archived": 0},
            {"role": "user", "content": "Inspect config"},
        ],
        child_key: [
            {"_type": "metadata", "key": child_key,
             "metadata": {SESSION_TYPE_KEY: SUBAGENT.name, PARENT_SESSION_KEY: parent_key,
                          TASK_METADATA_KEY: task_metadata},
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:01.200000",
             "last_archived": 0},
            {"role": "user", "content": "inspect"},
            {"role": "assistant", "content": "Verified"},
        ],
    }
    legacy = workspace / "sessions"
    legacy.mkdir(parents=True)
    for key, records in fixtures.items():
        (legacy / f"{SessionLocation.storage_key(key)}.jsonl").write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8",
        )
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in legacy.glob("*.jsonl")}

    for _ in range(2):
        manager, sessions, _ = manager_with_storage(workspace, root)
        try:
            assert {row["key"] for row in sessions.list_sessions()} == set(fixtures)
            assert sessions.child_session_keys(parent_key) == [child_key]
            status = manager.check(task_id, parent_key)
            assert status.state == "done" and status.result == "Verified"
            assert status.origin_turn_id == "turn-1"
            assert manager.get_running_count() == 0
            for key, records in fixtures.items():
                restored = sessions.read_session_file(key)
                assert restored["metadata"] == records[0]["metadata"]
                assert restored["messages"] == records[1:]
            assert list(legacy.glob("*.jsonl")) == []
            backups = sessions.sessions_dir / WORKSPACE_BACKUP_DIR
            assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in backups.glob("*.jsonl")} == source_hashes
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
    await sessions.state.update_metadata(child.key, {TASK_METADATA_KEY: "damaged"})
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    try:
        path = f"/api/sessions/{quote(parent.key, safe='')}/subagents"
        response = await gateway.http.dispatch(connection, Request(path, headers))
        assert response.status_code == 503
        assert "task history unavailable" in response.body.decode()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_scoped_task_history_queries_only_matching_children_and_all_active(tmp_path, monkeypatch):
    import nanobot.session.sqlite_store as sqlite_store

    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    manager._run_slots = asyncio.Semaphore(2)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Verified"))
    owner, other = "websocket:parent", "websocket:other"
    ids = {}
    entered, release = asyncio.Queue(), asyncio.Event()
    cancel_task = None

    async def hold(_spec):
        await entered.put(True)
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return AgentRunResult(messages=[], final_content="Finished")

    try:
        for label, parent, message_id, turn_id in (
            ("exact", owner, "prompt-in", "different-turn"),
            ("fallback", owner, "old-replay-id", "turn-in"),
            ("old", owner, "prompt-old", "turn-old"),
            ("unlinked", owner, None, None),
            ("unlinked-empty", owner, "", ""),
            ("half-linked", owner, "missing-prompt", None),
            ("foreign", other, "prompt-in", "turn-in"),
        ):
            await manager.run_inline(label, session_key=parent, origin_message_id=message_id,
                                     origin_turn_id=turn_id, runtime=runtime)
            ids[label] = next(tid for tid, status in manager._terminal_statuses.items()
                              if status.task_description == label)
        manager.runner.run = hold
        for label in ("running", "stopping"):
            await manager.spawn(label, session_key=owner, origin_message_id="off-page", runtime=runtime)
            await asyncio.wait_for(entered.get(), 15)
            ids[label] = next(tid for tid, record in manager._tasks.items()
                              if record.status.task_description == label)
        await manager.spawn("queued", session_key=owner, origin_message_id="off-page", runtime=runtime)
        ids["queued"] = next(tid for tid, record in manager._tasks.items()
                             if record.status.task_description == "queued")
        cancel_task = asyncio.create_task(manager.cancel(ids["stopping"], owner))
        for _ in range(1000):
            if manager._tasks[ids["stopping"]].status.state == "stopping":
                break
            await asyncio.sleep(0.01)
        assert manager._tasks[ids["stopping"]].status.state == "stopping"
        gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
        path = "/api/sessions/websocket%3Aparent/subagents"
        blocked = set()
        original_object = sqlite_store._object
        original_contains, original_status = manager.sessions.contains, manager.sessions.status

        def checked_object(raw):
            assert not any(f'"task_id":"{task_id}"' in raw for task_id in blocked), "decoded unrelated task"
            return original_object(raw)

        def checked_contains(task_id, parent):
            assert task_id not in blocked, "looked up unrelated retained task"
            return original_contains(task_id, parent)

        def checked_status(task_id, parent):
            assert task_id not in blocked, "read unrelated retained task"
            return original_status(task_id, parent)

        monkeypatch.setattr(sqlite_store, "_object", checked_object)
        monkeypatch.setattr(manager.sessions, "contains", checked_contains)
        monkeypatch.setattr(manager.sessions, "status", checked_status)
        active = {ids[name] for name in ("running", "stopping", "queued")}

        async def read(query):
            response = await gateway.http.dispatch(connection, Request(path + query, headers))
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
            return {task["task_id"]: task for task in json.loads(response.body)["tasks"]}

        blocked.update(ids[name] for name in ("old", "unlinked", "unlinked-empty", "half-linked", "foreign"))
        page = await read(f"?scope=page&task_id={ids['exact']}&task_id={ids['fallback']}")
        assert set(page) == active | {ids["exact"], ids["fallback"]}
        assert {page[ids[name]]["state"] for name in ("running", "stopping", "queued")} == {
            "running", "stopping", "queued",
        }
        blocked.update(ids[name] for name in ("exact", "fallback"))
        assert set(await read("?scope=page")) == active
        blocked.remove(ids["old"])
        assert set(await read(f"?scope=page&task_id={ids['old']}&task_id={ids['foreign']}")) == active | {ids["old"]}
        blocked.add(ids["old"])
        blocked.clear()
        assert set(await read("")) == set(ids.values()) - {ids["foreign"]}
        denied = await gateway.http.dispatch(connection, Request(path + "?scope=page", Headers()))
        assert denied.status_code == 401
    finally:
        release.set()
        if cancel_task is not None:
            await asyncio.gather(cancel_task, return_exceptions=True)
        await manager.close()
        await sessions.state.aclose()


@pytest.mark.asyncio
async def test_scoped_task_history_http_validation(tmp_path):
    manager, sessions, _ = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    path = "/api/sessions/websocket%3Aparent/subagents"
    try:
        valid = [
            "?scope=page", "?scope=page&task_id=x",
            "?" + urlencode([("scope", "page")] + [("task_id", "x")] * 80),
            "?" + urlencode({"scope": "page", "task_id": "é" * 256}),
        ]
        invalid = [
            "?scope=unknown", "?scope=", "?scope=page&scope=page", "?scope=unlinked&message_id=x",
            "?scope=page&message_id=", "?scope=page&turn_id=%20", "?scope=page&message_id=%00",
            "?scope=page&message_id=%FF", "?scope=page&message_id=%ZZ", "?scope=page&unknown=x",
            "?" + urlencode([("scope", "page")] + [("task_id", "x")] * 80 + [("task_id", "x")]),
            "?" + urlencode({"scope": "page", "task_id": "é" * 257}),
        ]
        for query in valid:
            assert (await gateway.http.dispatch(connection, Request(path + query, headers))).status_code == 200
        for query in invalid:
            assert (await gateway.http.dispatch(connection, Request(path + query, headers))).status_code == 400
        token = next(iter(gateway.tokens.api_tokens))
        assert (await gateway.http.dispatch(connection, Request(path + f"?scope=page&token={token}", Headers()))).status_code == 200
        assert (await gateway.http.dispatch(connection, Request(path + "?scope=unknown", Headers()))).status_code == 401
        assert (await gateway.http.dispatch(connection, Request(path.replace("websocket%3Aparent", "subagent%3Aother") + "?scope=page", headers))).status_code == 404
    finally:
        await manager.close()
        await sessions.state.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,selected", [
    ("finish", True),
    ("finish", False),
    ("newer-persisted", True),
    ("delete", True),
])
async def test_scoped_active_completion_after_index_read_is_refreshed(tmp_path, monkeypatch, outcome, selected):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    entered, finish = asyncio.Event(), asyncio.Event()
    loaded, release = asyncio.Event(), threading.Event()
    loop, owner_thread = asyncio.get_running_loop(), threading.get_ident()
    original_load, original_status = manager.sessions.load, manager.sessions.status
    refreshed = []
    request = None

    def observed_status(task_id, owner):
        refreshed.append(task_id)
        return original_status(task_id, owner)

    async def run(_spec):
        entered.set()
        await finish.wait()
        return AgentRunResult(messages=[], final_content="Verified")

    def paused_load(owner, scope):
        assert threading.get_ident() != owner_thread
        statuses = original_load(owner, scope)
        loop.call_soon_threadsafe(loaded.set)
        assert release.wait(15), "scoped history read was not released"
        return statuses

    manager.runner.run = run
    try:
        await manager.spawn("off-page", session_key="websocket:parent", origin_turn_id="off-page", runtime=runtime)
        await asyncio.wait_for(entered.wait(), 15)
        task_id, = manager._running_tasks
        previous_revision = manager._tasks[task_id].status.revision
        execution = manager._running_tasks[task_id]
        monkeypatch.setattr(manager.sessions, "load", paused_load)
        monkeypatch.setattr(manager.sessions, "status", observed_status)
        request = asyncio.create_task(gateway.http.dispatch(connection, Request(
            "/api/sessions/websocket%3Aparent/subagents?scope=page" + (f"&task_id={task_id}" if selected else ""), headers,
        )))
        await asyncio.wait_for(loaded.wait(), 15)
        finish.set()
        await asyncio.wait_for(execution, 15)
        if outcome == "newer-persisted":
            key = SubagentSessions.key(task_id)
            metadata = sessions.read_session_metadata(key)["metadata"][TASK_METADATA_KEY]
            metadata.update(revision=metadata["revision"] + 10, result="Newer persisted result")
            await sessions.state.update_metadata(key, {TASK_METADATA_KEY: metadata})
        elif outcome == "delete":
            await sessions.state.delete("websocket:parent")
        release.set()
        response = await asyncio.wait_for(request, 15)
        assert response.status_code == 200
        tasks = json.loads(response.body)["tasks"]
        if outcome == "delete":
            assert tasks == []
        else:
            assert task_id in refreshed
            if not selected:
                assert tasks == []
            else:
                task, = tasks
                assert task["task_id"] == task_id and task["state"] == "done"
                assert task["revision"] > previous_revision
                assert task["result"] == ("Newer persisted result" if outcome == "newer-persisted" else "Verified")
    finally:
        release.set()
        finish.set()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
        await manager.close()
        await sessions.state.aclose()


@pytest.mark.asyncio
async def test_scoped_read_handles_completion_before_terminal_status_is_saved(tmp_path, monkeypatch):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    entered, finish, finishing, save_terminal = (asyncio.Event() for _ in range(4))
    loaded, release_history = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    original_load, original_save = manager.sessions.load, manager._save_transcript
    request = None

    async def run(_spec):
        entered.set()
        await finish.wait()
        return AgentRunResult(messages=[], final_content="Verified")

    def paused_load(owner, scope):
        result = original_load(owner, scope)
        loop.call_soon_threadsafe(loaded.set)
        assert release_history.wait(15)
        return result

    async def paused_save(record):
        finishing.set()
        await save_terminal.wait()
        await original_save(record)

    manager.runner.run = run
    monkeypatch.setattr(manager, "_save_transcript", paused_save)
    try:
        await manager.spawn("off-page", session_key="websocket:parent", origin_turn_id="off-page", runtime=runtime)
        await asyncio.wait_for(entered.wait(), 15)
        task_id, = manager._running_tasks
        monkeypatch.setattr(manager.sessions, "load", paused_load)
        path = "/api/sessions/websocket%3Aparent/subagents"
        request = asyncio.create_task(gateway.http.dispatch(connection, Request(
            path + f"?scope=page&task_id={task_id}", headers,
        )))
        await asyncio.wait_for(loaded.wait(), 15)
        finish.set()
        await asyncio.wait_for(finishing.wait(), 15)
        assert manager.sessions.status(task_id, "websocket:parent").state == "running"
        release_history.set()
        response = await asyncio.wait_for(request, 15)
        task, = json.loads(response.body)["tasks"]
        assert task["task_id"] == task_id and task["state"] == "done" and task["result"] == "Verified"
        # A later empty page must not resurrect the still-persisted active observation.
        monkeypatch.setattr(manager.sessions, "load", original_load)
        response = await gateway.http.dispatch(connection, Request(path + "?scope=page", headers))
        assert json.loads(response.body)["tasks"] == []
    finally:
        release_history.set()
        finish.set()
        save_terminal.set()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
        await manager.close()
        await sessions.state.aclose()


@pytest.mark.asyncio
async def test_empty_scoped_page_refreshes_task_started_during_history_read(tmp_path, monkeypatch):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    before_query, loaded, entered, finish = (asyncio.Event() for _ in range(4))
    query, release = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    original_load, original_status = manager.sessions.load, manager.sessions.status
    refreshed = []
    request = None

    async def run(_spec):
        entered.set()
        await finish.wait()
        return AgentRunResult(messages=[], final_content="Verified")

    def paused_load(owner, scope):
        loop.call_soon_threadsafe(before_query.set)
        assert query.wait(15)
        statuses = original_load(owner, scope)
        loop.call_soon_threadsafe(loaded.set)
        assert release.wait(15)
        return statuses

    def observed_status(task_id, owner):
        refreshed.append(task_id)
        return original_status(task_id, owner)

    manager.runner.run = run
    try:
        await sessions.state.get("websocket:parent")
        monkeypatch.setattr(manager.sessions, "load", paused_load)
        monkeypatch.setattr(manager.sessions, "status", observed_status)
        request = asyncio.create_task(gateway.http.dispatch(connection, Request(
            "/api/sessions/websocket%3Aparent/subagents?scope=page", headers,
        )))
        await asyncio.wait_for(before_query.wait(), 15)
        await manager.spawn("started during read", session_key="websocket:parent", runtime=runtime)
        await asyncio.wait_for(entered.wait(), 15)
        task_id, = manager._running_tasks
        execution = manager._running_tasks[task_id]
        query.set()
        await asyncio.wait_for(loaded.wait(), 15)
        finish.set()
        await asyncio.wait_for(execution, 15)
        release.set()
        response = await asyncio.wait_for(request, 15)
        assert response.status_code == 200
        assert json.loads(response.body)["tasks"] == []
        assert task_id in refreshed
    finally:
        query.set()
        release.set()
        finish.set()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
        await manager.close()
        await sessions.state.aclose()


@pytest.mark.asyncio
async def test_page_selection_ignores_synthetic_origins_and_other_sessions(tmp_path, monkeypatch):
    import nanobot.session.sqlite_store as sqlite_store
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    owner, other = "websocket:parent", "websocket:other"
    history_turn = "subagent:" + "a" * 32
    canonical_turn = "session-input:" + "b" * 32
    detached_turn = "subagent:" + "c" * 32
    legacy_turn = "session-input:" + "d" * 32
    other_turn = "subagent:" + "e" * 32
    parent = sessions.get_or_create(owner)
    parent.add_message("user", "An older message", webui_turn_id=canonical_turn)
    sessions.save(parent)
    await sessions.state.append_history(owner, [HistoryFact(
        HistoryKind.INPUT, {"input_id": f"user:{history_turn}"}, turn_id=history_turn,
    )], expected_generation=parent.generation)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="Done"))
    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    try:
        ids = {}
        for name, parent_key, turn in (
            ("linked-history", owner, history_turn),
            ("linked-canonical", owner, canonical_turn),
            ("detached", owner, detached_turn),
            ("legacy", owner, legacy_turn),
            ("off-page", owner, "ordinary-old-turn"),
            ("foreign", other, other_turn),
        ):
            await manager.run_inline(name, session_key=parent_key, origin_turn_id=turn, runtime=runtime)
            ids[name] = next(tid for tid, status in manager._terminal_statuses.items()
                             if status.task_description == name)
        path = "/api/sessions/websocket%3Aparent/subagents"

        async def read(query):
            response = await gateway.http.dispatch(connection, Request(path + query, headers))
            assert response.status_code == 200
            return {item["task_id"] for item in json.loads(response.body)["tasks"]}

        # Simulate a terminal runtime snapshot before its final persisted status is saved.
        child_key = SubagentSessions.key(ids["linked-history"])
        stale = sessions.read_session_metadata(child_key)["metadata"][TASK_METADATA_KEY]
        stale.update(state="running", revision=stale["revision"] - 1)
        blocked = {ids[name] for name in ("linked-history", "linked-canonical", "off-page", "foreign")}
        object_, contains, status = sqlite_store._object, manager.sessions.contains, manager.sessions.status

        def checked_object(raw):
            assert not any(f'"task_id":"{task_id}"' in raw for task_id in blocked)
            return object_(raw)

        def checked_contains(task_id, parent_key):
            assert task_id not in blocked
            return contains(task_id, parent_key)

        def checked_status(task_id, parent_key):
            assert task_id not in blocked
            return status(task_id, parent_key)

        monkeypatch.setattr(sqlite_store, "_object", checked_object)
        monkeypatch.setattr(manager.sessions, "contains", checked_contains)
        monkeypatch.setattr(manager.sessions, "status", checked_status)
        # Origins do not select tasks, even when old turns resemble synthetic IDs.
        assert await read("?scope=page") == set()
        blocked.remove(ids["linked-history"])
        await sessions.state.update_metadata(child_key, {TASK_METADATA_KEY: stale})
        assert await read("?scope=page") == set()
        manager._terminal_statuses.clear()
        stale.update(state="done", revision=stale["revision"] + 1)
        await sessions.state.update_metadata(child_key, {TASK_METADATA_KEY: stale})
        blocked.add(ids["linked-history"])
        assert await read("?scope=page") == set()
        blocked.clear()
        assert await read(f"?scope=page&task_id={ids['linked-history']}") == {ids["linked-history"]}
        assert await read(f"?scope=page&task_id={ids['linked-canonical']}&task_id={ids['foreign']}") == {ids["linked-canonical"]}
    finally:
        await manager.close()
        await sessions.state.aclose()


@pytest.mark.asyncio
async def test_empty_page_refreshes_active_task_that_finishes_during_query(tmp_path, monkeypatch):
    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    owner, turn = "websocket:parent", "subagent:" + "f" * 32
    parent = await sessions.state.get(owner)
    await sessions.state.append_history(owner, [HistoryFact(
        HistoryKind.INPUT, {"input_id": f"user:{turn}"}, turn_id=turn,
    )], expected_generation=parent.generation)
    entered, finish, loaded = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release = threading.Event()
    event_loop = asyncio.get_running_loop()
    original_load = manager.sessions.load

    async def run(_spec):
        entered.set()
        await finish.wait()
        return AgentRunResult(messages=[], final_content="Done")

    def paused_load(parent_key, scope):
        result = original_load(parent_key, scope)
        event_loop.call_soon_threadsafe(loaded.set)
        assert release.wait(10)
        return result

    gateway, connection, headers = gateway_for(manager, sessions, tmp_path / "agent")
    manager.runner.run = run
    request = None
    try:
        await manager.spawn("Linked task", session_key=owner, origin_turn_id=turn, runtime=runtime)
        await asyncio.wait_for(entered.wait(), 10)
        task_id, = manager._running_tasks
        execution = manager._running_tasks[task_id]
        monkeypatch.setattr(manager.sessions, "load", paused_load)
        request = asyncio.create_task(gateway.http.dispatch(connection, Request(
            "/api/sessions/websocket%3Aparent/subagents?scope=page", headers,
        )))
        await asyncio.wait_for(loaded.wait(), 10)
        finish.set()
        await asyncio.wait_for(execution, 10)

        original_status = manager.sessions.status
        refreshed = []

        def observed_status(refreshed_id, parent):
            refreshed.append(refreshed_id)
            return original_status(refreshed_id, parent)

        monkeypatch.setattr(manager.sessions, "status", observed_status)
        release.set()
        response = await asyncio.wait_for(request, 10)
        assert response.status_code == 200
        assert json.loads(response.body)["tasks"] == []
        assert task_id in refreshed
    finally:
        release.set()
        finish.set()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
        await manager.close()
        await sessions.state.aclose()

@pytest.mark.asyncio
async def test_task_creation_persists_and_sends_independent_anchor(tmp_path):
    from nanobot.agent.tools.context import tool_call_context
    from nanobot.bus.runtime_events import SubagentAnchor
    from nanobot.webui.transcript import build_webui_thread_response

    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    owner = "websocket:parent"
    parent = await sessions.state.get(owner)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="done"))
    try:
        with request_context(RequestContext(
            channel="websocket", chat_id="parent", session_key=owner,
            session_generation=parent.generation, runtime=runtime, turn_id="turn-one",
            metadata={"_history_generation": parent.generation, "webui_turn_id": "turn-one"},
        )), tool_call_context("call-one"):
            await SubagentTool(manager).execute(action="create", task="inspect", wait=True)
        msg = await asyncio.wait_for(manager.bus.outbound.get(), 2)
        assert isinstance(msg.event, SubagentAnchor)
        assert msg.event.call_id == "call-one"
        task_id = msg.event.task_id
        before = sessions.project_history(owner, lambda snapshot: build_webui_thread_response(owner, history=snapshot))
        assert before is None or not any(event["event"] == "subagent_anchor" for event in before["events"])
        gateway, _, _ = gateway_for(manager, sessions, tmp_path / "agent")
        channel = WebSocketChannel(WebSocketConfig(), manager.bus, gateway=gateway)
        transport = MagicMock()
        channel._outbound._transport = transport
        transport.webui_recipients.return_value = (object(),)
        transport.webui_send_raw = AsyncMock()
        await channel._outbound.send(msg)
        sent = json.loads(transport.webui_send_raw.await_args.args[1])
        assert sent == {"event": "subagent_anchor", "chat_id": "parent", "task_id": task_id, "call_id": "call-one",
                        "turn_id": "turn-one", "turn_phase": "activity", "turn_seq": 1}
        response = sessions.project_history(owner, lambda snapshot: build_webui_thread_response(owner, history=snapshot))
        event = next(event for event in response["events"] if event["event"] == "subagent_anchor")
        assert (event["task_id"], event["call_id"]) == (task_id, "call-one")
    finally:
        await manager.close()
        await sessions.state.aclose()


@pytest.mark.asyncio
async def test_task_anchor_is_not_sent_to_a_different_webui_session(tmp_path):
    from nanobot.agent.tools.context import tool_call_context

    manager, sessions, runtime = manager_with_storage(tmp_path / "agent", tmp_path / "sessions")
    owner = "websocket:parent"
    await sessions.state.get(owner)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="done"))
    try:
        with request_context(RequestContext(
            channel="websocket", chat_id="different", session_key=owner,
            runtime=runtime, turn_id="turn-one",
        )), tool_call_context("call-one"):
            await SubagentTool(manager).execute(action="create", task="inspect", wait=True)
        assert manager.bus.outbound.empty()
        assert len(manager.statuses_for_session(owner)) == 1
    finally:
        await manager.close()
        await sessions.state.aclose()
