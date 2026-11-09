from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import httpx
import pytest
import websockets
from aiohttp import web

from nanobot.agent.subagent_sessions import SubagentSessions
from nanobot.agent.subagent_status import SubagentStatus
from nanobot.config.loader import load_config
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import PENDING_USER_TURN_KEY, RUNTIME_CHECKPOINT_KEY
from nanobot.webui.local_client_assets import LocalClientAssets
from nanobot.webui.remote_proxy import RemoteProxy
from nanobot.webui.remote_ssh import Tunnel

_BOOTSTRAP_SECRET = "smoke-secret"


async def test_remote_proxy_with_real_gateway_chat_settings_and_renewal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Python CI runs from a clean source tree without a frontend build. Supply
    # this transport smoke's own local shell instead of relying on build leftovers.
    assets = tmp_path / "local-dist"
    assets.mkdir()
    shell = "<!doctype html><title>Local smoke client</title>"
    (assets / "index.html").write_text(shell, encoding="utf-8")
    monkeypatch.setattr("nanobot.webui.remote_proxy.LocalClientAssets", lambda: LocalClientAssets(assets))
    ws_port, gateway_port = _free_port(), _free_port()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path, log_path = tmp_path / "config.json", tmp_path / "gateway.log"
    _write_smoke_config(config_path, workspace=workspace, ws_port=ws_port, gateway_port=gateway_port)
    process = _start_gateway(config_path, log_path)
    proxy = None
    try:
        upstream = _wait_for_bootstrap(f"http://127.0.0.1:{ws_port}", process, log_path)
        # The real gateway already owns this private listener. SSH pipe ownership
        # and shutdown are exercised separately by test_remote_proxy/remote_tunnel.
        transport = MagicMock(spec=Tunnel, port=ws_port, active=True,
                              pause=AsyncMock(), close=AsyncMock())
        proxy = await RemoteProxy.open(transport, _BOOTSTRAP_SECRET, upstream["terminal"]["gatewayId"])
        async with httpx.AsyncClient(trust_env=False) as client:
            assert (await client.get(proxy.origin + "/")).text == shell
            first = (await client.get(proxy.origin + "/webui/bootstrap", headers={
                "X-Nanobot-Auth": proxy.secret,
            })).json()
            assert _BOOTSTRAP_SECRET not in json.dumps(first)
            async with websockets.connect(first["ws_url"] + "?token=" + first["token"] + "&client_id=proxy-smoke") as ws:
                assert (await _recv_until(ws, "ready"))["client_id"] == "proxy-smoke"
                await ws.send(json.dumps({"type": "new_chat"}))
                chat_id = (await _recv_until(ws, "attached"))["chat_id"]
                await _recv_until(ws, "session_updated")
                await ws.send(json.dumps({"type": "message", "chat_id": chat_id,
                                         "content": "/model", "webui": True, "turn_id": "proxy-turn"}))
                assert "custom/smoke-model" in (await _recv_until(ws, "message"))["text"]
                await _recv_until(ws, "turn_end")
                await ws.send(json.dumps({"type": "webui_request", "request_id": "proxy-settings",
                                         "action": "settings.runtime_config.update",
                                         "payload": {"values": {"agents.defaults.max_tool_iterations": 2}}}))
                mutation = await _recv_until(ws, "webui_response")
                assert mutation["ok"] is True, mutation
                assert load_config(config_path).agents.defaults.max_tool_iterations == 2
            renewed = (await client.get(proxy.origin + "/webui/bootstrap", headers={
                "X-Nanobot-Auth": proxy.secret,
            })).json()
            assert renewed["token"] != first["token"]
            response = await client.get(proxy.origin + "/api/sessions", headers={
                "Authorization": "Bearer " + renewed["api_token"],
            })
            assert f"websocket:{chat_id}" in {row["key"] for row in response.json()["sessions"]}
    finally:
        if proxy is not None:
            await proxy.close()
        _stop_gateway(process)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_smoke_config(path: Path, *, workspace: Path, ws_port: int, gateway_port: int) -> None:
    config = {
        "agents": {
            "defaults": {
                "workspace": str(workspace),
                "provider": "custom",
                "model": "custom/smoke-model",
                "maxToolIterations": 1,
                "dream": {"enabled": False},
            }
        },
        "providers": {
            "custom": {
                "apiKey": "smoke-no-external-call",
                "apiBase": "http://127.0.0.1:9/v1",
            }
        },
        "channels": {
            "websocket": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": ws_port,
                "allowFrom": ["*"],
                "tokenIssueSecret": _BOOTSTRAP_SECRET,
            }
        },
        "gateway": {
            "host": "127.0.0.1",
            "port": gateway_port,
            "heartbeat": {"enabled": False},
        },
    }
    path.write_text(json.dumps(config), encoding="utf-8")


def _start_gateway(config_path: Path, log_path: Path) -> subprocess.Popen[bytes]:
    log_file = log_path.open("wb")
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "nanobot",
                "gateway",
                "--config",
                str(config_path),
            ],
            cwd=Path(__file__).resolve().parents[2],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
    finally:
        log_file.close()
    return process


def _stop_gateway(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        # Target only this gateway's console group and let it close its SQLite worker.
        # TerminateProcess also races the child behind a venv's Python launcher.
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.terminate()
    try:
        returncode = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        pytest.fail("gateway did not shut down gracefully within 30s")
    assert returncode == 0, f"gateway shutdown failed with exit code {returncode}"


def _get_json(url: str, *, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = httpx.get(url, headers=headers, timeout=5.0, trust_env=False)
    response.raise_for_status()
    return response.json()


def _get_bootstrap(url: str) -> dict:
    response = httpx.get(
        url,
        headers={"X-Nanobot-Auth": _BOOTSTRAP_SECRET},
        timeout=5.0,
        trust_env=False,
    )
    response.raise_for_status()
    return response.json()


def _wait_for_bootstrap(base_url: str, process: subprocess.Popen[bytes], log_path: Path) -> dict:
    deadline = time.monotonic() + 20
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            return _get_bootstrap(f"{base_url}/webui/bootstrap")
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
            time.sleep(0.2)
    logs = log_path.read_text(encoding="utf-8", errors="replace")
    raise AssertionError(f"gateway did not start; last_error={last_error!r}\n{logs}")


async def _recv_until(ws: websockets.WebSocketClientProtocol, event: str) -> dict:
    try:
        async with asyncio.timeout(20):
            while True:
                payload = json.loads(await ws.recv())
                if payload.get("event") == event:
                    return payload
    except TimeoutError as exc:
        raise AssertionError(f"websocket event {event!r} was not received within 20s") from exc


@pytest.mark.asyncio
async def test_gateway_webui_bootstrap_message_and_thread_hydration(tmp_path: Path) -> None:
    ws_port = _free_port()
    gateway_port = _free_port()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path = tmp_path / "config.json"
    log_path = tmp_path / "gateway.log"
    _write_smoke_config(
        config_path,
        workspace=workspace,
        ws_port=ws_port,
        gateway_port=gateway_port,
    )

    process = _start_gateway(config_path, log_path)
    base_url = f"http://127.0.0.1:{ws_port}"
    try:
        bootstrap = _wait_for_bootstrap(base_url, process, log_path)
        assert bootstrap["model_name"] == "custom/smoke-model"

        ws_url = f'{bootstrap["ws_url"]}?token={bootstrap["token"]}&client_id=smoke'
        async with websockets.connect(ws_url) as ws:
            ready = await _recv_until(ws, "ready")
            assert ready["client_id"] == "smoke"

            await ws.send(json.dumps({"type": "new_chat"}))
            attached = await _recv_until(ws, "attached")
            chat_id = attached["chat_id"]
            await _recv_until(ws, "session_updated")

            await ws.send(json.dumps({
                "type": "message",
                "chat_id": chat_id,
                "content": "/model",
                "webui": True,
                "turn_id": "smoke-turn",
            }))
            answer = await _recv_until(ws, "message")
            assert "Current model: `custom/smoke-model`" in answer["text"]
            await _recv_until(ws, "turn_end")

            await ws.send(json.dumps({
                "type": "message",
                "chat_id": chat_id,
                "content": "!echo shell-ok",
                "webui": True,
                "user_shell": True,
                "turn_id": "shell-turn",
            }))
            shell = await _recv_until(ws, "message")
            assert shell["text"].splitlines()[0] == "shell-ok"
            assert "Exit code: 0" in shell["text"]
            assert shell["render_as"] == "text"
            assert shell["turn_id"] == "shell-turn"
            await _recv_until(ws, "turn_end")

        api_token = _wait_for_bootstrap(base_url, process, log_path)["api_token"]
        sessions = _get_json(f"{base_url}/api/sessions", token=api_token)
        key = f"websocket:{chat_id}"
        assert key in {row["key"] for row in sessions["sessions"]}

        encoded_key = quote(key, safe="")
        thread = _get_json(
            f"{base_url}/api/sessions/{encoded_key}/webui-thread",
            token=api_token,
        )
        contents = [
            str(event.get("text") or "")
            for event in thread["events"]
            if event.get("event") in {"user_message", "message", "stream_end"}
        ]
        assert "/model" in contents
        assert any("Current model: `custom/smoke-model`" in text for text in contents)
        assert "!echo shell-ok" in contents
        assert shell["text"] in contents
        [shell_history] = [event for event in thread["events"] if event.get("event") == "message"
                           and event.get("turn_id") == "shell-turn"]
        assert shell_history["text"] == shell["text"]
        assert shell_history["render_as"] == shell["render_as"]
    finally:
        _stop_gateway(process)


@pytest.mark.asyncio
async def test_gateway_recovers_private_children_and_deletes_them_with_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path, log_path = tmp_path / "config.json", tmp_path / "gateway.log"
    ws_port, gateway_port = _free_port(), _free_port()
    _write_smoke_config(config_path, workspace=workspace, ws_port=ws_port, gateway_port=gateway_port)
    sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    parent = sessions.get_or_create("websocket:subagent-smoke")
    parent.add_message("user", "Inspect config")
    sessions.save(parent)
    children = SubagentSessions(sessions)
    now = time.monotonic()
    await children.create(SubagentStatus(
        task_id="finished", label="Finished", task_description="inspect", owner=parent.key,
        started_at=now, finished_at=now, completed_at=time.time(), state="done", phase="done", result="Verified",
    ))
    await children.create(SubagentStatus(
        task_id="abandoned", label="Abandoned", task_description="inspect", owner=parent.key,
        started_at=now, state="running", phase="thinking", result="Partial findings", partial=True,
        receipts={"follow-up": "accepted"},
    ))
    process = _start_gateway(config_path, log_path)
    base_url = f"http://127.0.0.1:{ws_port}"
    try:
        bootstrap = _wait_for_bootstrap(base_url, process, log_path)
        api_token = bootstrap["api_token"]
        path = f"{base_url}/api/sessions/{quote(parent.key, safe='')}/subagents"
        first = _get_json(path, token=api_token)
        tasks = {task["task_id"]: task for task in first["tasks"]}
        assert tasks["finished"]["state"] == "done"
        assert tasks["finished"]["result"] == "Verified"
        assert tasks["abandoned"]["state"] == "interrupted"
        assert tasks["abandoned"]["stop_reason"] == "host_restarted"
        assert tasks["abandoned"]["result"] == "Partial findings"
        assert tasks["abandoned"]["receipts"] == {"follow-up": "undelivered"}
        assert _get_json(path, token=api_token) == first
        sidebar = _get_json(f"{base_url}/api/sessions", token=api_token)
        assert {row["key"] for row in sidebar["sessions"]} == {parent.key}
        ws_url = bootstrap["ws_url"] + "?token=" + bootstrap["token"] + "&client_id=child-session-smoke"
        async with websockets.connect(ws_url) as ws:
            await _recv_until(ws, "ready")
            await ws.send(json.dumps({
                "type": "webui_request", "request_id": "delete-parent",
                "action": "session.delete", "payload": {"key": parent.key},
            }))
            response = await _recv_until(ws, "webui_response")
            assert response["ok"] is True, response
        assert sessions.read_session_file(parent.key) is None
        assert all(sessions.read_session_file(children.key(task_id)) is None for task_id in tasks)
    finally:
        _stop_gateway(process)


@pytest.mark.asyncio
async def test_desktop_terminal_identity_and_independent_client_lifetime(tmp_path: Path) -> None:
    ws_port, gateway_port = _free_port(), _free_port()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path, log_path = tmp_path / "config.json", tmp_path / "gateway.log"
    _write_smoke_config(config_path, workspace=workspace, ws_port=ws_port, gateway_port=gateway_port)
    process = _start_gateway(config_path, log_path)
    base_url = f"http://127.0.0.1:{ws_port}"
    try:
        first = _wait_for_bootstrap(base_url, process, log_path)
        terminal = first["terminal"]
        assert terminal["protocolVersion"] == 1
        unauthenticated = httpx.get(f"{base_url}/webui/terminal", trust_env=False)
        assert unauthenticated.status_code == 401
        probe = _get_bootstrap(f"{base_url}/webui/terminal")
        assert probe == terminal
        second = _get_bootstrap(f"{base_url}/webui/bootstrap")
        assert second["terminal"] == terminal
        identity_query = f'&terminal_protocol=1&terminal_instance={terminal["gatewayId"]}'
        first_url = f'{first["ws_url"]}?token={first["token"]}&client_id=terminal-one'
        with pytest.raises(websockets.exceptions.InvalidStatus) as wrong:
            async with websockets.connect(first_url + "&terminal_protocol=1&terminal_instance=wrong"):
                pytest.fail("Wrong gateway identity accepted")
        assert wrong.value.response.status_code == 409
        async with websockets.connect(first_url + identity_query) as one:
            assert (await _recv_until(one, "ready"))["terminal"] == terminal
            second_url = f'{second["ws_url"]}?token={second["token"]}&client_id=terminal-two'
            async with websockets.connect(second_url + identity_query) as two:
                assert (await _recv_until(two, "ready"))["terminal"] == terminal
                await one.close()
                await two.send(json.dumps({"type": "new_chat"}))
                chat_id = (await _recv_until(two, "attached"))["chat_id"]
                await two.send(json.dumps({"type": "message", "chat_id": chat_id,
                    "content": "/model", "webui": True, "turn_id": "terminal-model"}))
                assert "custom/smoke-model" in (await _recv_until(two, "message"))["text"]
                await _recv_until(two, "turn_end")
        assert process.poll() is None
        after = _get_bootstrap(f"{base_url}/webui/bootstrap")
        assert after["terminal"] == terminal
        async with websockets.connect(f'{after["ws_url"]}?token={after["token"]}&client_id=browser') as browser:
            assert "terminal" not in await _recv_until(browser, "ready")
    finally:
        _stop_gateway(process)


def test_gateway_restart_restores_a_completed_answer_without_replaying_model(
    tmp_path: Path,
) -> None:
    ws_port = _free_port()
    gateway_port = _free_port()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path = tmp_path / "config.json"
    first_log = tmp_path / "gateway-first.log"
    second_log = tmp_path / "gateway-second.log"
    _write_smoke_config(
        config_path,
        workspace=workspace,
        ws_port=ws_port,
        gateway_port=gateway_port,
    )
    base_url = f"http://127.0.0.1:{ws_port}"

    first = _start_gateway(config_path, first_log)
    try:
        _wait_for_bootstrap(base_url, first, first_log)
    finally:
        _stop_gateway(first)

    sessions_root = tmp_path / "sessions"
    sessions = SessionManager(workspace, sessions_root=sessions_root)
    session = sessions.get_or_create("websocket:recovery-smoke")
    session.messages.append({"role": "user", "content": "recover this answer"})
    session.metadata["webui"] = True
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "final_response",
        "assistant_message": {
            "role": "assistant",
            "content": "restored without another model request",
        },
        "completed_tool_results": [],
        "pending_tool_calls": [],
    }
    sessions.save(session)

    second = _start_gateway(config_path, second_log)
    try:
        bootstrap = _wait_for_bootstrap(base_url, second, second_log)
        deadline = time.monotonic() + 20
        restored = None
        while time.monotonic() < deadline:
            restored = SessionManager(
                workspace,
                sessions_root=sessions_root,
            ).get_or_create("websocket:recovery-smoke")
            if any(
                message.get("content") == "restored without another model request"
                for message in restored.messages
            ):
                break
            time.sleep(0.1)
        else:
            logs = second_log.read_text(encoding="utf-8", errors="replace")
            raise AssertionError(f"answer was not recovered after restart\n{logs}")

        assert restored is not None
        assert PENDING_USER_TURN_KEY not in restored.metadata
        assert RUNTIME_CHECKPOINT_KEY not in restored.metadata
        assert restored.metadata["webui_recovery"]["reason"] == "answer_restored"

        async def assert_attach_state() -> None:
            ws_url = f'{bootstrap["ws_url"]}?token={bootstrap["token"]}&client_id=recovery-smoke'
            async with websockets.connect(ws_url) as ws:
                await _recv_until(ws, "ready")
                await ws.send(json.dumps({"type": "attach", "chat_id": "recovery-smoke"}))
                attached = await _recv_until(ws, "attached")
                assert attached["recovery_state"]["status"] == "recovered"
                assert attached["recovery_state"]["reason"] == "answer_restored"

        asyncio.run(assert_attach_state())
    finally:
        _stop_gateway(second)


@pytest.mark.parametrize("stop_during_checkpoint", [False, True])
async def test_real_gateway_goal_single_run_and_stop(tmp_path: Path, stop_during_checkpoint: bool) -> None:
    """Exercise the actual gateway and WebSocket with a synthetic local model."""
    checkpoint_waiting = asyncio.Event()
    release_checkpoint = asyncio.Event()
    closing_request = asyncio.Event()
    release_close = asyncio.Event()
    requests: list[dict] = []

    async def barrier(_request: web.Request) -> web.Response:
        checkpoint_waiting.set()
        await release_checkpoint.wait()
        return web.Response(text="ready")

    async def model(request: web.Request) -> web.StreamResponse:
        payload = await request.json()
        is_title = any(
            "You write short, neutral chat titles" in str(message.get("content"))
            for message in payload.get("messages", [])
        )
        if is_title:
            text, reason, tool = "Synthetic goal", "stop", None
        else:
            requests.append(payload)
            number = len(requests)
            text, reason, tool = None, "tool_calls", None
            if number == 1:
                tool = ("create_goal", {"objective": "Verify the synthetic task."})
            elif number <= 16:
                tool = ("list_dir", {"path": "."})
            elif stop_during_checkpoint:
                assert number == 17
                assert "Handle this independent input" in str(payload["messages"])
                text, reason = "Handled independent input.", "content_filter"
            elif number == 17:
                closing_request.set()
                await release_close.wait()
                tool = ("update_goal", {"action": "complete", "recap": "Verified."})
            else:
                assert number == 18 and not payload.get("tools")
                text, reason = "Verified.", "stop"
        message: dict = {"role": "assistant", "content": text}
        if tool is not None:
            message["tool_calls"] = [{
                "id": f"call-{len(requests)}", "type": "function",
                "function": {"name": tool[0], "arguments": json.dumps(tool[1])},
            }]
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if not payload.get("stream"):
            return web.json_response({
                "id": "synthetic", "object": "chat.completion", "created": 1,
                "model": "smoke-model", "choices": [{"index": 0, "message": message, "finish_reason": reason}],
                "usage": usage,
            })
        delta: dict = {"role": "assistant"}
        if text is not None:
            delta["content"] = text
        if tool is not None:
            delta["tool_calls"] = [{"index": 0, **message["tool_calls"][0]}]
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for choice in (
            {"index": 0, "delta": delta, "finish_reason": None},
            {"index": 0, "delta": {}, "finish_reason": reason},
        ):
            chunk = {"id": "synthetic", "object": "chat.completion.chunk", "created": 1,
                     "model": "smoke-model", "choices": [choice], "usage": usage}
            await response.write(f"data: {json.dumps(chunk)}\n\n".encode())
        await response.write(b"data: [DONE]\n\n")
        return response

    app = web.Application()
    app.router.add_get("/barrier", barrier)
    app.router.add_post("/v1/chat/completions", model)
    server = web.AppRunner(app)
    await server.setup()
    site = web.TCPSite(server, "127.0.0.1", 0)
    await site.start()
    assert site._server is not None and site._server.sockets  # noqa: SLF001
    model_port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
    ws_port, gateway_port = _free_port(), _free_port()
    home, workspace = tmp_path / "home", tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    config_path, log_path = tmp_path / "config.json", tmp_path / "gateway.log"
    _write_smoke_config(config_path, workspace=workspace, ws_port=ws_port, gateway_port=gateway_port)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["providers"]["custom"]["apiBase"] = f"http://127.0.0.1:{model_port}/v1"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    launcher = """
import asyncio, faulthandler, httpx, sys
from pathlib import Path
from nanobot.session.state import SessionState
original = SessionState.checkpoint_view
barrier_url = sys.argv[3]
held = False
async def checkpoint(self, session, payload):
    global held
    await original(self, session, payload)
    results = payload.get('completed_tool_results', [])
    if barrier_url and not held and results and results[-1].get('tool_call_id') == 'call-16':
        held = True
        async with httpx.AsyncClient(trust_env=False, timeout=20) as client:
            response = await client.get(barrier_url)
            response.raise_for_status()
        await asyncio.Event().wait()
SessionState.checkpoint_view = checkpoint
home, config = sys.argv[1:3]
sys.argv = ['nanobot', '--home', home, 'gateway', '--config', config]
from nanobot.cli.entry import main
with Path(config).with_name('gateway-stacks.log').open('w') as stacks:
    faulthandler.dump_traceback_later(10, repeat=True, file=stacks)
    try:
        main()
    finally:
        faulthandler.cancel_dump_traceback_later()
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("NANOBOT_")}
    env.update({"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home),
                "LOCALAPPDATA": str(home), "TMP": str(tmp_path), "TEMP": str(tmp_path),
                "NO_PROXY": "localhost,127.0.0.1", "no_proxy": "localhost,127.0.0.1"})
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = None
    try:
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-c", launcher, str(home), str(config_path),
                 f"http://127.0.0.1:{model_port}/barrier" if stop_during_checkpoint else ""],
                cwd=Path(__file__).resolve().parents[2], env=env, stdout=log,
                stderr=subprocess.STDOUT, creationflags=creationflags,
            )
        bootstrap = await asyncio.to_thread(
            _wait_for_bootstrap, f"http://127.0.0.1:{ws_port}", process, log_path,
        )
        async with websockets.connect(bootstrap["ws_url"] + "?token=" + bootstrap["token"] + "&client_id=goal-e2e") as ws:
            await _recv_until(ws, "ready")
            await ws.send(json.dumps({"type": "new_chat"}))
            chat_id = (await _recv_until(ws, "attached"))["chat_id"]
            await _recv_until(ws, "session_updated")
            await ws.send(json.dumps({"type": "message", "chat_id": chat_id,
                                      "content": "/goal Verify the synthetic task",
                                      "webui": True, "turn_id": "goal-e2e"}))
            events: list[dict] = []

            async def receive_until(predicate):
                async with asyncio.timeout(20):
                    while True:
                        event = json.loads(await ws.recv())
                        events.append(event)
                        if predicate(event):
                            return event

            # Bound each model round, not all 16 durable rounds with one deadline.
            # Drain the real client while the gateway advances to the stop barrier.
            for request_count in range(1, 17):
                await receive_until(lambda event: (
                    event.get("event") == "model_request"
                    and event.get("phase") == "completed"
                    and event.get("usage", {}).get("request_count") == request_count
                ))

            if stop_during_checkpoint:
                await asyncio.wait_for(checkpoint_waiting.wait(), 20)
                await ws.send(json.dumps({"type": "message", "chat_id": chat_id,
                                          "content": "/stop", "webui": True}))
                end = await receive_until(lambda event: event.get("event") == "turn_end")
                assert end.get("outcome") == "cancelled"
                assert end["goal_state"]["status"] == "active"
                await receive_until(lambda event: event.get("event") == "goal_status" and event.get("status") == "idle")
                assert len(requests) == 16
                running = [event for event in events if event.get("event") == "goal_status" and event.get("status") == "running"]
                # Submitting Stop hydrates the current status before cancellation.
                assert {event.get("turn_id") for event in running} == {"goal-e2e"}
                assert running[0]["started_at"] > 0
                assert len({event["started_at"] for event in running}) == 1
                assert sum(event.get("event") == "turn_end" for event in events) == 1
                await ws.send(json.dumps({"type": "message", "chat_id": chat_id,
                                          "content": "Handle this independent input", "webui": True,
                                          "turn_id": "follow-up"}))
                followup = await receive_until(lambda event: event.get("event") == "turn_end")
                assert followup.get("turn_id") == "follow-up"
                assert len(requests) == 17
            else:
                await asyncio.wait_for(closing_request.wait(), 20)
                waiting = await receive_until(lambda event: (
                    event.get("event") == "model_request"
                    and event.get("phase") == "started"
                    and event.get("usage", {}).get("request_count") == 16
                ))
                assert waiting["usage"]["context_tokens"] == 10
                assert len(waiting["round_usages"]) == 8
                assert not any(event.get("event") == "turn_end" for event in events)
                history_url = f"http://127.0.0.1:{ws_port}/api/sessions/{quote('websocket:' + chat_id, safe='')}/webui-thread"
                headers = {"Authorization": f"Bearer {bootstrap['api_token']}"}
                async with httpx.AsyncClient(trust_env=False) as client:
                    modern = await client.get(history_url, params={"include_model_requests": "1"}, headers=headers)
                    modern.raise_for_status()
                    persisted = [event for event in modern.json()["events"] if event["event"] == "model_request"]
                    assert persisted[-1]["request_id"] == waiting["request_id"]
                    assert persisted[-1]["usage"] == waiting["usage"]
                    legacy = await client.get(history_url, headers={**headers, "If-None-Match": modern.headers["etag"]})
                    assert legacy.status_code == 200
                    assert not any(event["event"] == "model_request" for event in legacy.json()["events"])
                release_close.set()
                end = await receive_until(lambda event: event.get("event") == "turn_end")
                assert end.get("turn_id") == "goal-e2e"
                assert not end["goal_state"]["active"]
                assert len(requests) == 18
                await receive_until(lambda event: event.get("event") == "goal_status" and event.get("status") == "idle")
                assert sum(event.get("event") == "goal_status" and event.get("status") == "running" for event in events) == 1
                assert sum(event.get("event") == "turn_end" for event in events) == 1
                assert any(event.get("event") == "goal_state" and event.get("goal_state", {}).get("active") for event in events)
                reconnect_bootstrap = await asyncio.to_thread(_get_bootstrap, f"http://127.0.0.1:{ws_port}/webui/bootstrap")
                async with websockets.connect(reconnect_bootstrap["ws_url"] + "?token=" + reconnect_bootstrap["token"] + "&client_id=goal-reconnect") as reconnected:
                    await _recv_until(reconnected, "ready")
                    await reconnected.send(json.dumps({"type": "attach", "chat_id": chat_id}))
                    await _recv_until(reconnected, "attached")
                    state = await _recv_until(reconnected, "goal_state")
                    assert state["goal_state"] == {"active": False}
    finally:
        release_close.set()
        release_checkpoint.set()
        try:
            if process is not None and process.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    process.terminate()
                try:
                    # Keep the test model/barrier server live while its client exits.
                    await asyncio.to_thread(process.wait, timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=10)
                    stacks = tmp_path / "gateway-stacks.log"
                    if stacks.exists():
                        frames = re.findall(r'File "[^"\n]*[/\\]([^/\\"\n]+)", line (\d+) in (\w+)',
                                            stacks.read_text(encoding="utf-8"))
                        print("Gateway shutdown stack locations:", frames[-80:])
                    raise
        finally:
            await server.cleanup()
