from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config

runner = CliRunner()


@dataclass
class _Payload:
    message: str
    channel: str | None
    to: str | None
    deliver: bool


@dataclass
class _CronJob:
    id: str
    payload: _Payload


class _Bus:
    def __init__(self):
        self.outbound = []

    async def publish_outbound(self, msg):
        self.outbound.append(msg)

    async def publish_inbound(self, _msg):
        return None

    async def consume_outbound(self):
        await asyncio.sleep(5)
        return SimpleNamespace(content="", metadata={})


class _AgentLoop:
    def __init__(self, **kwargs):
        self.model = "fake-model"
        self.channels_config = SimpleNamespace(send_tool_hints=True, send_progress=True)
        self._stopped = False

    async def process_direct(self, *args, **kwargs):
        return "ok-response"

    async def run(self):
        await asyncio.sleep(0)

    def stop(self):
        self._stopped = True

    async def close_mcp(self):
        return None


class _ChannelManager:
    def __init__(self, _config: Config, _bus: _Bus, enabled: list[str] | None = None):
        self.enabled_channels = enabled or ["telegram"]
        self.channels = {name: object() for name in self.enabled_channels}

    async def start_all(self):
        await asyncio.sleep(0)

    async def stop_all(self):
        await asyncio.sleep(0)


class _CronService:
    def __init__(self, _path: Path):
        self.on_job = None

    def status(self):
        return {"jobs": 1}

    async def start(self):
        if self.on_job is not None:
            await self.on_job(_CronJob("j1", _Payload("cron-msg", "telegram", "42", True)))

    def stop(self):
        return None


class _HeartbeatService:
    def __init__(self, *, on_execute, on_notify, **kwargs):
        self._on_execute = on_execute
        self._on_notify = on_notify

    async def start(self):
        out = await self._on_execute("heartbeat-task")
        await self._on_notify(out)

    def stop(self):
        return None


class _SessionManager:
    def __init__(self, _workspace: Path):
        self._items = [{"key": "telegram:42"}]

    def list_sessions(self):
        return list(self._items)


def test_gateway_runs_cron_and_heartbeat_callbacks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    cfg.gateway.heartbeat.enabled = True

    bus = _Bus()

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.config.loader.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: bus)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _AgentLoop)
    monkeypatch.setattr("nanobot.session.manager.SessionManager", _SessionManager)
    monkeypatch.setattr("nanobot.cron.service.CronService", _CronService)
    monkeypatch.setattr("nanobot.heartbeat.service.HeartbeatService", _HeartbeatService)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _ChannelManager)

    out = runner.invoke(app, ["gateway", "--port", "19000"])
    assert out.exit_code == 0
    assert "Starting nanobot gateway" in out.stdout
    assert "Channels enabled" in out.stdout
    assert "Heartbeat" in out.stdout
    assert len(bus.outbound) >= 1


def test_agent_single_message_and_interactive_exit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.config.loader.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", _Bus)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _AgentLoop)
    monkeypatch.setattr("nanobot.cron.service.CronService", _CronService)

    class _Timer:
        def __init__(self, *_args, **_kwargs):
            self.daemon = True

        def start(self):
            return None

        def cancel(self):
            return None

    monkeypatch.setattr("threading.Timer", _Timer)

    single = runner.invoke(app, ["agent", "-m", "hello", "--timeout", "1"])
    assert single.exit_code == 0
    assert "nanobot" in single.stdout

    monkeypatch.setattr("nanobot.cli.commands._init_prompt_session", lambda: None)
    monkeypatch.setattr("nanobot.cli.commands._flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("nanobot.cli.commands._restore_terminal", lambda: None)

    calls = {"n": 0}

    async def _read_once():
        calls["n"] += 1
        return "exit"

    monkeypatch.setattr("nanobot.cli.commands._read_interactive_input_async", _read_once)

    interactive = runner.invoke(app, ["agent", "--session", "cli:direct", "--timeout", "0"])
    assert interactive.exit_code == 0
    assert "Interactive mode" in interactive.stdout
