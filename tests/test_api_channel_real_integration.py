"""Real API integration test for API channel -> AgentLoop -> model provider.

This test is skipped by default and only runs when:
  NANOBOT_RUN_REAL_API_TEST=1
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
import websockets


def _pick_free_port() -> int:
    """Pick an available localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _default_config_path() -> Path:
    return Path.home() / ".nanobot" / "config.json"


def _has_provider_credentials(cfg: dict[str, Any]) -> bool:
    """Best-effort check for available provider credentials."""
    providers = cfg.get("providers", {})
    if not isinstance(providers, dict):
        return False

    for value in providers.values():
        if not isinstance(value, dict):
            continue
        if value.get("apiKey"):
            return True

    agent_provider = (
        ((cfg.get("agents") or {}).get("defaults") or {}).get("provider") or "auto"
    )
    # OAuth providers may not store apiKey in config.
    return agent_provider in {"openai_codex", "github_copilot"}


async def _wait_gateway_ready(uri: str, timeout_s: float) -> None:
    """Poll websocket endpoint until gateway API channel is ready."""
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            async with websockets.connect(uri, open_timeout=1) as ws:
                ready_raw = await asyncio.wait_for(ws.recv(), timeout=3)
                ready = json.loads(ready_raw)
                if ready.get("type") == "ready":
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(0.2)

    raise TimeoutError(f"Gateway API not ready: {last_error}")


async def _run_chat_once(uri: str) -> dict[str, Any]:
    """Send one real chat turn and wait for final model message."""
    request_id = "real-api-test-1"
    async with websockets.connect(uri, open_timeout=5) as ws:
        ready_raw = await asyncio.wait_for(ws.recv(), timeout=5)
        ready = json.loads(ready_raw)
        assert ready.get("type") == "ready"

        await ws.send(
            json.dumps(
                {
                    "type": "chat",
                    "senderId": "real_test_user",
                    "chatId": "real_test_room",
                    "requestId": request_id,
                    "content": "请只回复：收到",
                },
                ensure_ascii=False,
            )
        )

        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            payload = json.loads(raw)
            msg_type = payload.get("type")
            if msg_type == "error":
                pytest.fail(f"API channel returned error: {payload}")
            if msg_type == "message":
                return payload

    raise TimeoutError("No final API message within timeout")


def test_api_channel_real_model_call() -> None:
    """Real integration: API channel should invoke model and persist logs."""
    if os.getenv("NANOBOT_RUN_REAL_API_TEST") != "1":
        pytest.skip("Set NANOBOT_RUN_REAL_API_TEST=1 to run real model integration test.")

    config_path = Path(
        os.getenv("NANOBOT_REAL_API_CONFIG", str(_default_config_path()))
    ).expanduser()
    if not config_path.exists():
        pytest.skip(f"Config not found: {config_path}")

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if not _has_provider_credentials(cfg):
        pytest.skip("No provider credentials detected in config.")

    port = _pick_free_port()
    cfg.setdefault("gateway", {})
    cfg["gateway"]["host"] = "127.0.0.1"
    cfg["gateway"]["port"] = port
    cfg.setdefault("channels", {})
    cfg["channels"]["api"] = {
        "enabled": True,
        "path": "/chat",
        "token": "",
        "allowFrom": ["*"],
    }

    repo_root = Path(__file__).resolve().parents[1]
    python_exe = Path(sys.executable)

    with TemporaryDirectory(prefix="nanobot_real_api_test_") as tmp:
        tmp_path = Path(tmp)
        runtime_config = tmp_path / "config.json"
        runtime_config.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        proc = subprocess.Popen(
            [str(python_exe), "-m", "nanobot", "gateway", "--config", str(runtime_config)],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

        try:
            uri = f"ws://127.0.0.1:{port}/chat"
            asyncio.run(_wait_gateway_ready(uri, timeout_s=45))
            final_msg = asyncio.run(_run_chat_once(uri))

            assert final_msg.get("type") == "message"
            assert final_msg.get("chatId") == "real_test_room"
            assert final_msg.get("requestId") == "real-api-test-1"
            content = final_msg.get("content")
            assert isinstance(content, str) and content.strip()

            log_file = tmp_path / "logs" / "api" / "chat_events.jsonl"
            assert log_file.exists()
            rows = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            events = {row.get("event") for row in rows}
            assert "inbound" in events
            assert "outbound" in events
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
