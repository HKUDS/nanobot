"""Remote setup discovers metadata, not secrets, and never invents sudo access."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.webui import remote_discovery, remote_ssh
from nanobot.webui.remote_instances import RemoteInstances
from nanobot.webui.remote_ssh import RemoteError, RemoteProfile

if sys.platform != "win32":
    import pwd


def locate(monkeypatch, capsys, path, units="", properties=""):
    calls = []

    def systemctl(args, **kwargs):
        calls.append(args)
        assert args[0] == "systemctl" and "sudo" not in args
        assert kwargs["timeout"] == 2
        return SimpleNamespace(returncode=0, stdout=units if "list-units" in args else properties)

    monkeypatch.setattr(sys, "argv", ["locate", str(path)])
    monkeypatch.setattr(subprocess, "run", systemctl)
    exec(remote_discovery._LOCATE, {})
    result = json.loads(capsys.readouterr().out.split("NANOBOT_REMOTE:")[1])
    assert "model-secret" not in json.dumps(result)
    return result, calls


def test_default_config_found_without_reading_contents(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.json"
    path.write_text("model-secret")  # Even invalid config content isn't read by discovery.
    result, calls = locate(monkeypatch, capsys, path)
    assert result["candidates"] == [{"config_path": str(path), "runtime_user": "", "service": ""}]
    assert len(calls) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="systemd account discovery targets Unix servers")
def test_service_account_and_private_path_are_offered_without_sudo(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".nanobot/config.json"
    original_stat = Path.stat

    def stat(self, *args, **kwargs):
        if self == path:
            raise PermissionError
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_dir=str(tmp_path)))
    result, calls = locate(monkeypatch, capsys, tmp_path / "missing.json",
                           "nanobot-team.service loaded active running\n",
                           "Id=nanobot-team.service\nUser=nanobot\nWorkingDirectory=/opt/nanobot\nExecStart=/opt/nanobot/bin/nanobot gateway\n")
    assert result["candidates"] == [{"config_path": str(path), "runtime_user": "nanobot", "service": "nanobot-team.service"}]
    assert len(calls) == 2


@pytest.mark.skipif(sys.platform == "win32", reason="systemd account discovery targets Unix servers")
def test_multiple_configs_and_custom_service_path(tmp_path, monkeypatch, capsys):
    default = tmp_path / "default.json"
    custom = tmp_path / "custom config.json"
    default.touch()
    custom.touch()
    user = pwd.getpwuid(os.getuid()).pw_name
    result, _ = locate(monkeypatch, capsys, default, "nanobot.service loaded active running\n",
                       f'Id=nanobot.service\nUser={user}\nWorkingDirectory={tmp_path}\nExecStart=nanobot gateway --config "custom config.json"\n')
    assert [item["config_path"] for item in result["candidates"]] == [str(default), str(custom)]
    assert all(not item["runtime_user"] for item in result["candidates"])


def test_unavailable_systemctl_keeps_default_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["locate", str(tmp_path / "absent")])
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=FileNotFoundError))
    exec(remote_discovery._LOCATE, {})
    result = json.loads(capsys.readouterr().out.split("NANOBOT_REMOTE:")[1])
    assert result["candidates"] == []
    assert result["incomplete"] is True


async def test_inspection_uses_login_user_and_strips_unexpected_data(monkeypatch):
    check = AsyncMock(return_value={"hostname": "server", "candidates": [{
        "config_path": "/srv/bot/config.json", "runtime_user": "nanobot", "service": "nanobot.service", "secret": "model-secret",
    }], "incomplete": False, "secret": "model-secret"})
    monkeypatch.setattr(remote_discovery, "run_check", check)
    result = await remote_discovery.inspect(RemoteProfile(name="Test", host="server", runtime_user="root"))
    assert check.call_args.args[0].runtime_user == ""
    assert "model-secret" not in json.dumps(result)


@pytest.mark.parametrize("result", [
    {"hostname": "server", "candidates": [{"config_path": "/tmp/x\n", "runtime_user": ""}], "incomplete": False},
    {"hostname": "server", "candidates": [{"config_path": "/tmp/x", "runtime_user": "-root"}], "incomplete": False},
    {"hostname": "server", "candidates": [{}] * 9, "incomplete": False},
    {"hostname": "server", "candidates": "bad", "incomplete": False},
])
async def test_malformed_inspection_is_rejected(monkeypatch, result):
    monkeypatch.setattr(remote_discovery, "run_check", AsyncMock(return_value=result))
    with pytest.raises(RemoteError, match="probe_failed"):
        await remote_discovery.inspect(RemoteProfile(name="Test", host="server"))


async def test_inspection_reuses_host_verification_without_opening_tunnel(tmp_path, monkeypatch):
    manager = RemoteInstances(tmp_path)
    key = (await manager.action("save", {"profile": {"name": "Test", "host": "server"}}))["id"]
    check = AsyncMock(side_effect=RemoteError("host_key_unknown"))
    monkeypatch.setattr(remote_discovery, "inspect", check)
    with pytest.raises(RemoteError, match="host_key_unknown"):
        await manager.action("inspect", {"id": key})
    assert key in manager._unknown_hosts
    assert not manager.connections
    check.side_effect = None
    check.return_value = {"hostname": "server", "candidates": [], "incomplete": False}
    before = manager.path.read_bytes()
    assert (await manager.action("inspect", {"id": key}))["candidates"] == []
    assert manager.path.read_bytes() == before


async def test_cancelled_inspection_reaps_remote_process(monkeypatch):
    process = MagicMock(returncode=None)
    process.communicate = AsyncMock(side_effect=asyncio.CancelledError)
    process.wait = AsyncMock(return_value=0)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(asyncio.CancelledError):
        await remote_discovery.inspect(RemoteProfile(name="Test", host="server"))
    process.terminate.assert_called_once()


@pytest.mark.parametrize(("message", "code"), [
    (b"kex_exchange_identification: Connection closed by remote host", "ssh_connection_closed"),
    (b"Connection reset by peer", "ssh_connection_closed"),
    (b"connect to host server port 22: Connection refused", "ssh_refused"),
    (b"Could not resolve hostname server", "ssh_host_not_found"),
    (b"Too many authentication failures", "ssh_too_many_keys"),
])
def test_setup_errors_are_actionable_without_leaking_server_output(message, code):
    assert remote_ssh.ssh_error(message) == code
