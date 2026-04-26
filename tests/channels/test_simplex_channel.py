"""Tests for the SimpleX bridge launcher channel."""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.channels.simplex import SimplexChannel


@pytest.mark.asyncio
async def test_login_runs_bridge_with_active_config_path(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    script_path = repo_root / "bridge" / "simplex_bridge.py"
    config_path = tmp_path / "config.json"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("", encoding="utf-8")
    (repo_root / "nanobot").mkdir()

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return MagicMock()

    monkeypatch.setattr("nanobot.channels.simplex._bridge_script_path", lambda: script_path)
    monkeypatch.setattr("nanobot.channels.simplex.get_config_path", lambda: config_path)
    monkeypatch.setattr("nanobot.channels.simplex.subprocess.run", fake_run)

    channel = SimplexChannel({"enabled": True}, MagicMock())

    assert await channel.login() is True
    assert calls == [
        (
            (
                [sys.executable, str(script_path), "--config", str(config_path)],
            ),
            {"check": True, "cwd": repo_root},
        )
    ]


@pytest.mark.asyncio
async def test_start_launches_bridge_process(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    script_path = repo_root / "bridge" / "simplex_bridge.py"
    config_path = tmp_path / "config.json"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("", encoding="utf-8")
    (repo_root / "nanobot").mkdir()

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    channel = SimplexChannel({"enabled": True}, MagicMock())

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 0

        async def wait(self) -> int:
            channel._running = False
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr("nanobot.channels.simplex._bridge_script_path", lambda: script_path)
    monkeypatch.setattr("nanobot.channels.simplex.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "nanobot.channels.simplex.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    await channel.start()

    assert calls == [
        (
            (sys.executable, str(script_path), "--config", str(config_path)),
            {"cwd": repo_root},
        )
    ]


@pytest.mark.asyncio
async def test_stop_terminates_running_bridge():
    channel = SimplexChannel({"enabled": True}, MagicMock())

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.terminate = MagicMock()
            self.kill = MagicMock()
            self.wait = AsyncMock(return_value=0)

    process = FakeProcess()
    channel._process = process
    channel._running = True

    await channel.stop()

    assert channel.is_running is False
    process.terminate.assert_called_once_with()
    process.wait.assert_awaited()
    process.kill.assert_not_called()


@pytest.mark.asyncio
async def test_send_raises_runtime_error():
    channel = SimplexChannel({"enabled": True}, MagicMock())

    with pytest.raises(RuntimeError, match="websocket channel"):
        await channel.send(MagicMock())


def test_channels_login_simplex_uses_builtin_channel(monkeypatch):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    from nanobot.config.schema import Config

    runner = CliRunner()
    seen: dict[str, object] = {}

    async def fake_login(self, force: bool = False) -> bool:
        seen["force"] = force
        seen["config"] = self.config
        return True

    monkeypatch.setattr(
        "nanobot.config.loader.load_config",
        lambda config_path=None: Config.model_validate({"channels": {"simplex": {"enabled": False}}}),
    )
    monkeypatch.setattr("nanobot.channels.simplex.SimplexChannel.login", fake_login)

    result = runner.invoke(app, ["channels", "login", "simplex", "--force"])

    assert result.exit_code == 0
    assert seen["force"] is True
    assert seen["config"].enabled is False
