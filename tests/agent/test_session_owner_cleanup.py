import asyncio
import os
import sys

import pytest

from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.session.manager import SessionPolicy
from nanobot.webui.gateway_services import build_gateway_services


async def start_exec(agent, key, workspace):
    manager = agent._exec_session_manager
    sid, _ = await manager.start(
        command=[sys.executable, "-I", "-c", "import sys; sys.stdin.readline()"],
        cwd=str(workspace), env=dict(os.environ), timeout=30, shell_program=None,
        login=False, yield_time_ms=0, max_output_chars=1000, owner_session_key=key,
    )
    return manager._sessions[sid].process


async def test_archive_stops_new_owner_and_delete_stops_restored_owner(loop_factory, tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    agent = loop_factory()
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=agent.bus, session_manager=agent.sessions,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
        discard_session=agent.discard_session, stop_session=agent.stop_session,
    )
    owner, retained = "websocket:first", "websocket:second"

    async def archive(*keys):
        result = await gateway.http.dispatch_webui_mutation(
            None, "sidebar.update", {"state": {"archived_keys": list(keys)}},
        )
        assert result.status_code == 200
        return result.result["archived_keys"]

    started, finished = asyncio.Event(), asyncio.Event()

    async def run_child(_spec):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    monkeypatch.setattr(agent.subagents.runner, "run", run_child)
    try:
        session = await agent.sessions.state.get(owner)
        await agent.sessions.state.get(retained)
        await archive(retained)
        keep = await start_exec(agent, retained, tmp_path)
        stop = await start_exec(agent, owner, tmp_path)
        await agent.subagents.spawn("child", session_key=owner, runtime=await agent.runtime_for_session(session))
        await asyncio.wait_for(started.wait(), 3)
        assert await archive(owner, retained, "websocket:missing") == [owner, retained]
        assert finished.is_set() and stop.returncode is not None
        assert (await agent.sessions.state.read(owner)).generation == session.generation
        await archive(owner, retained)
        await archive(owner)
        assert keep.returncode is None
        result = await gateway.http.dispatch_webui_mutation(None, "session.delete", {"key": retained})
        assert result.result["deleted"] and keep.returncode is not None
    finally:
        await agent.aclose()


@pytest.mark.parametrize("persisted", [False, True])
async def test_direct_temporary_parent_cleanup_respects_durable_owner(loop_factory, tmp_path, monkeypatch, persisted):
    agent = loop_factory()
    key = "cli:direct"
    process = None

    async def turn(*args, **kwargs):
        nonlocal process
        process = await start_exec(agent, key, tmp_path)

    monkeypatch.setattr(agent, "_process_message", turn)
    try:
        if persisted:
            await agent.sessions.state.get(key)
        await agent.process_direct("test", session_key=key, ephemeral=True, _session_policy=SessionPolicy(persist=False))
        assert process is not None
        assert (process.returncode is None) == persisted
        assert (await agent.sessions.state.read(key) is not None) == persisted
    finally:
        await agent.aclose()
