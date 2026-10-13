"""A regular cloud login can complete pairing without guessing a sudo command."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from nanobot.cli import remote
from nanobot.cli.remote import _default_ssh_user
from nanobot.webui import remote_pair_server
from nanobot.webui.remote_pairing import PairStore, read_request
from nanobot.webui.remote_ssh import RemoteError


@pytest.fixture
def protected(monkeypatch, tmp_path):
    request = PairStore(tmp_path / "local").start()["command"].split()[-1]
    host_key = read_request(request).ssh_key
    config = tmp_path / "service account" / "config.json"
    monkeypatch.setattr(remote.sys, "platform", "linux")
    monkeypatch.setattr(remote.os, "getuid", lambda: 1001, raising=False)
    monkeypatch.setattr(remote, "_default_ssh_user", lambda: "ubuntu")
    monkeypatch.setattr(remote, "_default_host", lambda: "8.8.8.8")
    monkeypatch.setattr(remote.shutil, "which", lambda _: "/usr/bin/sudo")
    original_read = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **kw:
                        host_key if path.name == "ssh_host_ed25519_key.pub"
                        else original_read(path, *a, **kw))
    metadata = Mock(side_effect=RemoteError("config_permission"))
    authorize = Mock()
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(remote_pair_server, "metadata", metadata)
    monkeypatch.setattr(remote_pair_server, "authorize", authorize)
    monkeypatch.setattr(remote.subprocess, "run", run)
    return SimpleNamespace(request=request, config=config, metadata=metadata, authorize=authorize,
                           run=run, args=["pair", request, "--config", str(config)])


def test_explicit_admin_consent_keeps_environment_config_and_login(protected, monkeypatch):
    python = str(protected.config.parent / ".venv" / "bin" / "python")
    monkeypatch.setattr(remote.sys, "executable", python)
    result = CliRunner().invoke(remote.app, protected.args, input="y\n")
    assert result.exit_code == 0, result.output
    assert "Continue as server administrator?" in result.output
    assert "File permissions will not change" in result.output
    protected.run.assert_called_once_with([
        "/usr/bin/sudo", "--", python, "-I", "-m", "nanobot",
        "remote", "pair", protected.request, "--config", str(protected.config), "--port", "22",
        "--host", "8.8.8.8", "--ssh-user", "ubuntu",
    ], check=False)
    protected.authorize.assert_not_called()


@pytest.mark.parametrize("answer", ["n\n", "\n", ""])
def test_decline_or_closed_stdin_never_escalates(protected, answer):
    result = CliRunner().invoke(remote.app, protected.args, input=answer)
    assert result.exit_code in (0, 1)
    assert "Continue as server administrator?" in result.output
    protected.run.assert_not_called()
    protected.authorize.assert_not_called()


def test_explicit_options_survive_sudo(protected):
    result = CliRunner().invoke(remote.app, protected.args + ["--host", "server.example",
                                "--ssh-user", "deploy", "--port", "2222"], input="y\n")
    assert result.exit_code == 0
    argv = protected.run.call_args.args[0]
    assert argv[argv.index("--host") + 1] == "server.example"
    assert argv[argv.index("--ssh-user") + 1] == "deploy"
    assert argv[argv.index("--port") + 1] == "2222"


@pytest.mark.parametrize("root", [False, True])
def test_missing_sudo_or_denied_root_has_manual_recovery_without_recursion(protected, monkeypatch, root):
    monkeypatch.setattr(remote.os, "getuid", lambda: 0 if root else 1001)
    if not root:
        monkeypatch.setattr(remote.shutil, "which", lambda _: None)
    result = CliRunner().invoke(remote.app, protected.args)
    assert result.exit_code == 1
    assert "Ask the administrator" in result.output
    assert "Do not make the config publicly readable" in result.output
    assert "Continue as server administrator?" not in result.output
    protected.run.assert_not_called()


def test_sudo_failure_keeps_error_and_gives_retry(protected):
    protected.run.return_value.returncode = 1
    result = CliRunner().invoke(remote.app, protected.args, input="y\n")
    assert result.exit_code == 1
    assert "Pairing did not finish" in result.output
    assert "get a new command if it has expired" in result.output
    protected.authorize.assert_not_called()


def test_other_config_error_does_not_offer_sudo(protected):
    protected.metadata.side_effect = RemoteError("pair_webui_auth_required")
    result = CliRunner().invoke(remote.app, protected.args)
    assert result.exit_code == 1
    assert "Continue as server administrator?" not in result.output
    protected.run.assert_not_called()


def test_invalid_request_never_offers_sudo(protected):
    result = CliRunner().invoke(remote.app, ["pair", "not-a-request", "--config", str(protected.config)])
    assert result.exit_code == 1
    protected.metadata.assert_not_called()
    protected.run.assert_not_called()


def test_readable_config_still_requires_device_authorization(protected):
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    result = CliRunner().invoke(remote.app, protected.args + ["--host", "example.com"], input="n\n")
    assert result.exit_code == 0
    assert "Authorize this computer?" in result.output
    assert "Cancelled. No device was authorized" in result.output
    assert "Continue as server administrator?" not in result.output
    protected.run.assert_not_called()
    protected.authorize.assert_not_called()


def test_expired_request_never_offers_sudo(protected, monkeypatch):
    from nanobot.webui import remote_pairing

    now = remote_pairing.time.time()
    monkeypatch.setattr(remote_pairing.time, "time", lambda: now + 601)
    result = CliRunner().invoke(remote.app, protected.args)
    assert result.exit_code == 1
    assert "pair_expired" in result.output
    protected.run.assert_not_called()


def test_unavailable_sudo_process_fails_without_authorizing(protected):
    protected.run.side_effect = subprocess.SubprocessError()
    result = CliRunner().invoke(remote.app, protected.args, input="y\n")
    assert result.exit_code == 1
    protected.authorize.assert_not_called()


def test_discovered_service_config_is_carried_into_admin_retry(protected):
    protected.run.side_effect = [SimpleNamespace(stdout="NANOBOT_REMOTE:" + json.dumps({
        "hostname": "team", "incomplete": False, "candidates": [{"config_path": str(protected.config),
        "runtime_user": "nanobot", "service": "nanobot-team.service"}],
    })), SimpleNamespace(returncode=0)]
    result = CliRunner().invoke(remote.app, ["pair", protected.request], input="y\n")
    assert result.exit_code == 0, result.output
    argv = protected.run.call_args.args[0]
    assert argv[argv.index("--config") + 1] == str(protected.config)
    assert argv[argv.index("--ssh-user") + 1] == "ubuntu"
    assert protected.run.call_count == 2


def test_protected_parent_directory_offers_same_recovery(protected, monkeypatch):
    original = Path.resolve
    def resolve(path, *args, **kwargs):
        if path == protected.config:
            raise PermissionError
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolve)
    result = CliRunner().invoke(remote.app, protected.args, input="n\n")
    assert result.exit_code == 0, result.output
    assert "Continue as server administrator?" in result.output
    protected.metadata.assert_not_called()
    protected.run.assert_not_called()


def test_detected_address_skips_ip_prompt_and_identifies_this_server(protected):
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    result = CliRunner().invoke(remote.app, protected.args, input="n\n")
    assert result.exit_code == 0, result.output
    assert "on this server (ubuntu@8.8.8.8)" in result.output
    assert "This server's public IP or hostname:" not in result.output
    assert "Could not detect" not in result.output
    protected.authorize.assert_not_called()


def test_manual_fallback_names_this_server_not_the_local_computer(protected, monkeypatch):
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    monkeypatch.setattr(remote, "_default_host", lambda: "")
    result = CliRunner().invoke(remote.app, protected.args, input="43.156.243.141\nn\n")
    assert result.exit_code == 0, result.output
    assert "This server's public IP or hostname:" in result.output
    assert "not your computer's IP" in result.output
    assert "on this server (ubuntu@43.156.243.141)" in result.output
    protected.authorize.assert_not_called()


def test_explicit_host_skips_address_detection(protected, monkeypatch):
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    detect = Mock()
    monkeypatch.setattr(remote, "_default_host", detect)
    result = CliRunner().invoke(remote.app, protected.args + ["--host", "server.example"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "on this server (ubuntu@server.example)" in result.output
    detect.assert_not_called()


def test_root_console_with_two_accounts_goes_straight_to_device_consent(protected, monkeypatch):
    pwd = pytest.importorskip("pwd")
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    monkeypatch.setattr(remote.os, "getuid", lambda: 0)
    monkeypatch.setattr(pwd, "getpwuid", lambda _: SimpleNamespace(pw_uid=0, pw_name="root"))
    monkeypatch.delenv("SUDO_USER", raising=False)
    monkeypatch.setattr(remote, "_ssh_login_users", lambda: ["lighthouse", "ubuntu"])
    monkeypatch.setattr(remote, "_cloud_ssh_user", lambda: "ubuntu")
    monkeypatch.setattr(remote, "_default_ssh_user", _default_ssh_user)
    result = CliRunner().invoke(remote.app, protected.args, input="n\n")
    assert result.exit_code == 0, result.output
    assert "on this server (ubuntu@8.8.8.8)" in result.output
    assert "Authorize this computer?" in result.output
    assert "SSH login account" not in result.output
    assert "Choose an account" not in result.output
    protected.authorize.assert_not_called()


def test_ambiguous_accounts_are_numbered_and_explained_before_consent(protected, monkeypatch):
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    monkeypatch.setattr(remote, "_default_ssh_user", lambda: None)
    monkeypatch.setattr(remote, "_ssh_login_users", lambda: ["deploy", "ubuntu"])
    result = CliRunner().invoke(remote.app, protected.args, input="not-a-number\n0\n3\n2\nn\n")
    assert result.exit_code == 0, result.output
    assert "1. deploy" in result.output and "2. ubuntu" in result.output
    assert "not your cloud website account" in result.output
    assert "No password is needed here" in result.output
    assert "on this server (ubuntu@8.8.8.8)" in result.output
    assert "SSH login account:" not in result.output
    assert result.output.count("Choose an account number") == 4
    assert result.output.count("Please choose a number from 1 to 2") == 2
    protected.authorize.assert_not_called()


def test_account_picker_can_be_cancelled_without_authorizing(protected, monkeypatch):
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    monkeypatch.setattr(remote, "_default_ssh_user", lambda: None)
    monkeypatch.setattr(remote, "_ssh_login_users", lambda: ["deploy", "ubuntu"])
    result = CliRunner().invoke(remote.app, protected.args, input="")
    assert result.exit_code == 1, result.output
    assert "Authorize this computer?" not in result.output
    protected.authorize.assert_not_called()


def test_no_login_accounts_explains_recovery_without_asking_for_a_name(protected, monkeypatch):
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    monkeypatch.setattr(remote, "_default_ssh_user", lambda: None)
    monkeypatch.setattr(remote, "_ssh_login_users", lambda: [])
    result = CliRunner().invoke(remote.app, protected.args)
    assert result.exit_code == 1, result.output
    assert "No regular login account was found on this server" in result.output
    assert "No device was authorized" in result.output
    assert "Choose an account number" not in result.output
    assert "Authorize this computer?" not in result.output
    protected.authorize.assert_not_called()


def test_explicit_account_skips_discovery_and_selection(protected, monkeypatch):
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    choose = Mock(side_effect=AssertionError("explicit account must win"))
    monkeypatch.setattr(remote, "_choose_ssh_user", choose)
    result = CliRunner().invoke(remote.app, protected.args + ["--ssh-user", "deploy"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "on this server (deploy@8.8.8.8)" in result.output
    choose.assert_not_called()
    protected.authorize.assert_not_called()


def test_multiple_nanobots_keep_invalid_choices_in_the_selection_step(protected):
    protected.metadata.side_effect = None
    protected.metadata.return_value = {"port": 8765}
    protected.run.return_value = SimpleNamespace(stdout="NANOBOT_REMOTE:" + json.dumps({
        "hostname": "team", "incomplete": False, "candidates": [
            {"config_path": str(protected.config), "runtime_user": "nanobot", "service": "nanobot-team.service"},
            {"config_path": str(protected.config.parent / "other.json"), "runtime_user": "nanobot", "service": "other.service"},
        ],
    }))
    result = CliRunner().invoke(remote.app, ["pair", protected.request], input="0\n3\n1\nn\n")
    assert result.exit_code == 0, result.output
    assert result.output.count("Which nanobot?") == 3
    assert result.output.count("Please choose a number from 1 to 2") == 2
    protected.metadata.assert_called_once_with(protected.config)
    protected.authorize.assert_not_called()
