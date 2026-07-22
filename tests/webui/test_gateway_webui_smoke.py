"""Black-box smoke test for the real gateway WebUI transport."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
import websockets

_BOOTSTRAP_SECRET = "smoke-secret"


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
        )
    finally:
        log_file.close()
    return process


def _stop_gateway(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


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
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        payload = json.loads(raw)
        if payload.get("event") == event:
            return payload
    raise AssertionError(f"websocket event {event!r} was not received")


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

        api_token = _wait_for_bootstrap(base_url, process, log_path)["api_token"]
        sessions = _get_json(f"{base_url}/api/sessions", token=api_token)
        key = f"websocket:{chat_id}"
        assert key in {row["key"] for row in sessions["sessions"]}

        encoded_key = quote(key, safe="")
        thread = _get_json(
            f"{base_url}/api/sessions/{encoded_key}/webui-thread",
            token=api_token,
        )
        contents = [str(message.get("content") or "") for message in thread["messages"]]
        assert "/model" in contents
        assert any("Current model: `custom/smoke-model`" in text for text in contents)
    finally:
        _stop_gateway(process)
