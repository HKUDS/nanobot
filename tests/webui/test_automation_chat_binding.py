"""Move a complete scheduled turn through the real authenticated gateway."""

import asyncio
import json
import socket
import uuid
from contextlib import suppress
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import websockets

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import current_request_context
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.schema import Config
from nanobot.cron.binding import CronBinding, binding_revision
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.service import CronService
from nanobot.cron.types import CronRunRecord, CronSchedule
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager
from nanobot.webui.automation_chats import automation_chats
from nanobot.webui.automation_results import cron_run_response
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.session_automations import serialize_automation_jobs
from nanobot.webui.workspaces import WebUIWorkspaceController


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")


def seed(tmp_path):
    sessions = SessionManager(tmp_path / "workspace")
    for key, title, route in [
        ("websocket:source", "Daily report", None),
        ("telegram:-100:topic:42", "Product team", {
            "channel": "telegram", "chat_id": "-100",
            "metadata": {"message_thread_id": 42, "sender_id": "must-not-copy"},
        }),
    ]:
        session = sessions.get_or_create(key)
        session.metadata["title"] = title
        if route:
            session.metadata["_compaction_route"] = route
        session.add_message("user", title)
        sessions.save(session)
    cron = CronService(tmp_path / "cron" / "jobs.json")
    job = cron.add_job(
        "Daily report", CronSchedule(kind="every", every_ms=86400000), "Summarize",
        session_key="websocket:source", origin_channel="websocket", origin_chat_id="source",
    )
    return sessions, cron, job


def target_binding():
    return CronBinding("telegram:-100:topic:42", "telegram", "-100", {"message_thread_id": 42})


@pytest.mark.asyncio
async def test_durable_move_stale_edit_failed_save_and_old_action(tmp_path, monkeypatch):
    _, cron, job = seed(tmp_path)
    await cron.start()
    try:
        old = cron.get_job(job.id)
        revision = binding_revision(old)
        before = cron.store_path.read_bytes()
        write = cron._atomic_write
        def fail(*args):
            raise OSError("disk full")
        monkeypatch.setattr(cron, "_atomic_write", fail)
        with pytest.raises(OSError, match="disk full"):
            cron.change_binding(job.id, revision=revision, binding=target_binding(), message="New")
        assert cron.store_path.read_bytes() == before
        assert cron.get_job(job.id) == old
        monkeypatch.setattr(cron, "_atomic_write", write)
        moved = cron.change_binding(job.id, revision=revision, binding=target_binding(), message="New")
        assert moved.state == old.state
        assert moved.enabled == old.enabled
        assert moved.schedule == old.schedule
        assert CronService(cron.store_path).get_job(job.id) == moved
        with pytest.raises(ValueError, match="changed"):
            cron.change_binding(job.id, revision=revision, binding=target_binding(), message="Stale")
        # A CLI process can have read the old job before the WebUI commits.
        cron._append_action("update", asdict(old))
        assert cron.get_job(job.id) == moved
        # A directory-sync failure after replace must not report a false rollback.
        def committed_then_failed(path, content):
            write(path, content)
            raise OSError("directory sync failed")
        monkeypatch.setattr(cron, "_atomic_write", committed_then_failed)
        moved = cron.change_binding(job.id, revision=binding_revision(moved),
                                    binding=target_binding(), message="Committed")
        assert cron.get_job(job.id).payload.message == moved.payload.message == "Committed"
    finally:
        cron.stop()


@pytest.mark.asyncio
async def test_running_job_cannot_move(tmp_path):
    _, cron, job = seed(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    async def execute(_job):
        entered.set()
        await release.wait()
    cron.on_job = execute
    await cron.start()
    task = asyncio.create_task(cron.run_job(job.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        with pytest.raises(ValueError, match="busy"):
            cron.change_binding(job.id, revision=binding_revision(job),
                                binding=target_binding(), message="New")
        assert cron.get_job(job.id).payload.session_key == "websocket:source"
    finally:
        release.set()
        await task
        cron.stop()


@pytest.mark.asyncio
async def test_legacy_run_identity_is_captured_before_the_first_move(tmp_path):
    _, cron, job = seed(tmp_path)
    await cron.start()
    try:
        cron.get_job(job.id).state.run_history.append(CronRunRecord(run_at_ms=123, status="ok"))
        cron._save_store()
        moved = cron.change_binding(job.id, revision=binding_revision(cron.get_job(job.id)),
                                    binding=target_binding(), message="Reviewed")
        assert moved.state.run_history[0].session_key == "websocket:source"
        assert CronService(cron.store_path).get_job(job.id).state.run_history == moved.state.run_history
    finally:
        cron.stop()


def test_target_identity_scope_and_channel_lifecycle(tmp_path):
    sessions, _, job = seed(tmp_path)
    (tmp_path / "other").mkdir()
    workspaces = WebUIWorkspaceController(session_manager=sessions,
        default_workspace=tmp_path / "workspace", default_restrict_to_workspace=False)
    for key, metadata in [
        ("websocket:other-project", {"workspace_scope": {"project_path": str(tmp_path / "other"), "access_mode": "full"}}),
        ("websocket:restricted", {"workspace_scope": {"project_path": str(tmp_path / "workspace"), "access_mode": "restricted"}}),
        ("telegram:old-ambiguous", {}),
        ("unified:default", {"_compaction_route": {"channel": "telegram", "chat_id": "-100"}}),
    ]:
        session = sessions.get_or_create(key)
        session.metadata.update(metadata)
        sessions.save(session)
    chats = automation_chats(job, sessions, workspaces, {"telegram": {"running": True}})
    assert {chat.binding.session_key for chat in chats} == {"websocket:source", "telegram:-100:topic:42"}
    target = next(chat for chat in chats if chat.title == "Product team")
    assert target.binding == target_binding()
    assert set(target.public_payload()) == {"id", "title", "channel"}
    assert "-100" not in json.dumps(target.public_payload())
    assert len(automation_chats(job, sessions, workspaces, {})) == 1
    job.payload.session_key = "telegram:-100:topic:42"
    job.payload.origin_channel = "telegram"
    job.payload.origin_chat_id = "-100"
    offline = automation_chats(job, sessions, workspaces, {})
    current = next(chat for chat in offline if chat.title == "Product team")
    assert current.public_payload()["unavailable"] is True
    # Only identical display names need a visible disambiguator.
    session = sessions.get_or_create("websocket:source")
    session.metadata["title"] = "Product team"
    sessions.save(session)
    duplicates = automation_chats(job, sessions, workspaces, {})
    assert len({chat.title for chat in duplicates}) == 2
    assert all(" · @" in chat.title for chat in duplicates)


def test_untitled_chat_uses_message_preview_until_renamed(tmp_path):
    sessions, _, job = seed(tmp_path)
    chat = sessions.get_or_create("websocket:reminder")
    chat.add_message("user", "十分钟后提醒我喝水")
    sessions.save(chat)
    workspaces = WebUIWorkspaceController(session_manager=sessions,
        default_workspace=tmp_path / "workspace", default_restrict_to_workspace=False)
    chats = automation_chats(job, sessions, workspaces, {})
    choice = next(item for item in chats if item.binding.session_key == chat.key)
    assert choice.public_payload()["title"] == "十分钟后提醒我喝水"
    chat.metadata.update(title="My reminders", title_user_edited=True)
    sessions.save(chat)
    renamed = next(item for item in automation_chats(job, sessions, workspaces, {})
                   if item.binding.session_key == chat.key)
    assert renamed.id == choice.id
    assert renamed.title == "My reminders"


async def mutate(ws, values, job_id):
    request_id = str(uuid.uuid4())
    await ws.send(json.dumps({"type": "webui_request", "request_id": request_id,
        "action": "automation.change_chat", "payload": {"id": job_id, "values": values}}))
    async with asyncio.timeout(5):
        while True:
            response = json.loads(await ws.recv())
            if response.get("request_id") == request_id and response.get("event") == "webui_response":
                return response


@pytest.mark.asyncio
@pytest.mark.parametrize("target_channel", ["telegram", "websocket"])
async def test_real_gateway_move_run_reload_and_previous_result(tmp_path, target_channel):
    sessions, cron, job = seed(tmp_path)
    if target_channel == "websocket":
        target_session = sessions.get_or_create("websocket:destination")
        target_session.metadata["title"] = "Report inbox"
        target_session.add_message("user", "Report inbox")
        sessions.save(target_session)
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=100)
    provider.can_resume_conversation_state.return_value = False
    provider.estimate_prompt_tokens.return_value = (100, "test")
    requests = []
    async def reply(**kwargs):
        requests.append(kwargs["messages"])
        return LLMResponse(content="Synthetic result")
    provider.chat_stream_with_retry = reply
    bus = MessageBus()
    agent = AgentLoop(bus=bus, provider=provider, workspace=tmp_path / "workspace",
        model="test-model", session_manager=sessions, tools_config=Config().tools)
    agent.tools.get_definitions = MagicMock(return_value=[])
    async def execute(job):
        return await run_bound_cron_job(job, agent=agent, cron=cron)
    cron.on_job = execute
    await cron.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    cfg = WebSocketConfig.model_validate({"enabled": True, "host": "127.0.0.1", "port": port,
        "path": "/ws", "allowFrom": ["*"], "websocketRequiresToken": True,
        "tokenIssueSecret": "synthetic-access-secret"})
    gateway = build_gateway_services(config=cfg, bus=bus, session_manager=sessions,
        static_dist_path=None, workspace_path=tmp_path / "workspace", default_restrict_to_workspace=False,
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None,
        cron_service=cron, channel_runtime_status=lambda: {"telegram": {"running": True}})
    channel = WebSocketChannel(cfg, bus, gateway=gateway)
    server = asyncio.create_task(channel.start())
    client = None
    try:
        assert await cron.run_job(job.id)
        old = cron.get_job(job.id)
        old_run = old.state.run_history[-1]
        token = gateway.tokens.issue_token(60, audience="webui")
        async with asyncio.timeout(5):
            while client is None:
                try:
                    client = await websockets.connect(f"ws://127.0.0.1:{port}/ws?token={token}")
                except OSError:
                    await asyncio.sleep(.01)
        assert json.loads(await client.recv())["event"] == "ready"
        api_token = gateway.tokens.issue_api_token(60)
        async with httpx.AsyncClient(trust_env=False) as http:
            session_jobs = await http.get(
                f"http://127.0.0.1:{port}/api/sessions/websocket%3Asource/automations",
                headers={"Authorization": f"Bearer {api_token}"},
            )
            assert session_jobs.status_code == 200
            detail = session_jobs.json()["jobs"][0]
            assert detail["origin"]["session_key"] == "websocket:source"
            assert detail["origin"]["title"] == "Daily report"
            assert detail["protected"] is False
            assert detail["chat_binding_revision"] == binding_revision(old)
            assert detail["state"]["run_history"][0]["status"] == "ok"
            url = f"http://127.0.0.1:{port}/api/webui/automations/chats?id={job.id}"
            assert (await http.get(url)).status_code == 401
            result = await http.get(url, headers={"Authorization": f"Bearer {api_token}"})
            assert result.status_code == 200
            data = result.json()
            target = next(chat for chat in data["chats"]
                          if chat["title"] == ("Product team" if target_channel == "telegram" else "Report inbox"))
            direct = await http.get(
                f"http://127.0.0.1:{port}/api/webui/automations/change-chat?id={job.id}",
                headers={"Authorization": f"Bearer {api_token}"},
            )
            assert direct.status_code == 405
        values = {"target_id": target["id"], "revision": data["revision"], "message": "Summarize this chat"}
        assert not (await mutate(client, {**values, "chat_id": "forged"}, job.id))["ok"]
        assert not (await mutate(client, {**values, "revision": "stale"}, job.id))["ok"]
        assert not (await mutate(client, {**values, "target_id": "forged"}, job.id))["ok"]
        changed = await mutate(client, values, job.id)
        assert changed["ok"], changed
        moved = CronService(cron.store_path).get_job(job.id)
        assert moved.payload.origin_metadata == ({"message_thread_id": 42} if target_channel == "telegram" else {})
        assert moved.state.next_run_at_ms == old.state.next_run_at_ms
        assert cron_run_response(cron.store_path.parent / "runs", moved, old_run) == "Synthetic result"
        assert not (await mutate(client, values, job.id))["ok"]
        assert await cron.run_job(job.id)
        assert target["title"] in json.dumps(requests[-1])
        assert "Daily report" not in json.dumps(requests[-1])
        outgoing = []
        while bus.outbound_size:
            outgoing.append(await bus.consume_outbound())
        target_chat_id = "-100" if target_channel == "telegram" else "destination"
        delivered = [msg for msg in outgoing if msg.content == "Synthetic result" and msg.chat_id == target_chat_id]
        assert len(delivered) == 1
        assert delivered[0].channel == target_channel
        if target_channel == "telegram":
            assert delivered[0].metadata["message_thread_id"] == 42
        moved = CronService(cron.store_path).get_job(job.id)
        for run in moved.state.run_history:
            assert cron_run_response(cron.store_path.parent / "runs", moved, run) == "Synthetic result"
        history = serialize_automation_jobs([moved], include_details=True)[0]["state"]["run_history"]
        expected_history = ["websocket:source", None if target_channel == "telegram" else "websocket:destination"]
        assert [run["webui_session_key"] for run in history] == expected_history
        await agent.process_direct("Explain the report you just sent.",
            session_key=moved.payload.session_key, channel=target_channel, chat_id=target_chat_id)
        assert any(row.get("role") == "assistant" and row.get("content") == "Synthetic result"
                   for row in requests[-1])
        if target_channel == "websocket":
            for msg in outgoing:
                if msg.channel == "websocket":
                    await channel.send(msg)
            async with httpx.AsyncClient(trust_env=False) as http:
                opened = await http.get(
                    f"http://127.0.0.1:{port}/api/sessions/websocket%3Adestination/webui-thread",
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                assert opened.status_code == 200
                assert "Synthetic result" in opened.text
            async def delete(confirm=False):
                request_id = str(uuid.uuid4())
                await client.send(json.dumps({"type": "webui_request", "request_id": request_id,
                    "action": "session.delete", "payload": {
                        "key": "websocket:destination", "delete_automations": confirm,
                    }}))
                async with asyncio.timeout(5):
                    while True:
                        response = json.loads(await client.recv())
                        if response.get("request_id") == request_id:
                            assert response["ok"], response
                            return response["result"]
            blocked = await delete()
            assert blocked["blocked_by_automations"]
            assert blocked["automations"][0]["id"] == job.id
            assert cron.get_job(job.id) is not None
            assert (await delete(confirm=True))["deleted"]
            assert cron.get_job(job.id) is None
            assert sessions.read_session_file("websocket:destination") is None
            assert sessions.read_session_file("websocket:source") is not None
            assert not await cron.run_job(job.id)
            return
        cron.change_binding(job.id, revision=binding_revision(moved),
                            binding=CronBinding("websocket:source", "websocket", "source", {}), message="Back")
        # Moving back must not turn the external run's link into the current chat.
        history = serialize_automation_jobs([cron.get_job(job.id)], include_details=True)[0]["state"]["run_history"]
        assert [run["webui_session_key"] for run in history] == expected_history
    finally:
        if client is not None:
            await client.close()
        await channel.stop()
        await asyncio.wait_for(server, 5)
        cron.stop()
        await agent.aclose()


@pytest.mark.asyncio
async def test_late_subagent_result_stays_with_moved_task(tmp_path, monkeypatch):
    # A background result can arrive after the normal 300-second terminal wait.
    monkeypatch.setattr("nanobot.agent.loop._SUBAGENT_TERMINAL_WAIT_SECONDS", 0.02)
    sessions, cron, job = seed(tmp_path)
    release = asyncio.Event()
    entered = asyncio.Event()
    started = False
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=100)
    provider.can_resume_conversation_state.return_value = False
    provider.estimate_prompt_tokens.return_value = (100, "test")
    async def reply(**kwargs):
        nonlocal started
        ctx = current_request_context()
        assert ctx is not None
        if ctx.session_key.startswith("subagent:"):
            entered.set()
            await release.wait()
            return LLMResponse(content="37 items completed")
        assert ctx.session_key == "telegram:-100:topic:42"
        if ctx.sender_id == "subagent":
            return LLMResponse(content="Final report: 37 items completed")
        if not started:
            started = True
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="background-report", name="subagent", arguments={
                    "action": "create", "task": "Prepare the report", "wait": False,
                },
            )], finish_reason="tool_calls")
        return LLMResponse(content="Preparing the report")
    provider.chat_stream_with_retry = reply
    bus = MessageBus()
    agent = AgentLoop(bus=bus, provider=provider, workspace=tmp_path / "workspace",
        model="test-model", session_manager=sessions, tools_config=Config().tools)
    consumer = asyncio.create_task(agent.run())
    await cron.start()
    try:
        moved = cron.change_binding(job.id, revision=binding_revision(job),
                                    binding=target_binding(), message="Prepare the report")
        await asyncio.wait_for(run_bound_cron_job(moved, agent=agent, cron=cron), 5)
        await asyncio.wait_for(entered.wait(), 5)
        release.set()
        delivered = []
        async with asyncio.timeout(5):
            while not any(msg.content.startswith("Final report:") for msg in delivered):
                msg = await bus.consume_outbound()
                if msg.event is None and msg.content:
                    delivered.append(msg)
        assert [(msg.channel, msg.chat_id) for msg in delivered] == [("telegram", "-100")] * 2
        assert "Final report: 37 items completed" in json.dumps(
            sessions.read_session_file("telegram:-100:topic:42"))
        assert "37 items completed" not in json.dumps(sessions.read_session_file("websocket:source"))
    finally:
        release.set()
        cron.stop()
        agent.stop()
        consumer.cancel()
        with suppress(asyncio.CancelledError):
            await consumer
        await agent.aclose()
