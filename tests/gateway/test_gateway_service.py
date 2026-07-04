import os
import plistlib

from blackcat.gateway import GatewayStartOptions
from blackcat.gateway.service import GatewayServiceInstaller, GatewayServiceOptions


def _expected_launchd_domain() -> str:
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return "gui/current"
    return f"gui/{getuid()}"


def test_systemd_install_dry_run_renders_user_unit(tmp_path):
    installer = GatewayServiceInstaller(platform_name="Linux", home=tmp_path)

    result = installer.install(
        GatewayServiceOptions(
            start=GatewayStartOptions(
                port=18790,
                verbose=True,
                workspace="/tmp/blackcat workspace",
                config_path="/tmp/blackcat/config.json",
            ),
            python_executable="/venv/bin/python",
        ),
        dry_run=True,
    )

    assert result.ok is True
    assert result.manager == "systemd"
    assert result.path == tmp_path / ".config/systemd/user/blackcat-gateway.service"
    assert ("systemctl", "--user", "daemon-reload") in result.commands
    assert ("systemctl", "--user", "enable", "blackcat-gateway.service") in result.commands
    assert ("systemctl", "--user", "restart", "blackcat-gateway.service") in result.commands
    assert result.content is not None
    assert 'WorkingDirectory="/tmp/blackcat workspace"' in result.content
    assert 'ExecStart=/venv/bin/python -m blackcat gateway --foreground --port 18790 --verbose' in result.content
    assert '--workspace "/tmp/blackcat workspace" --config /tmp/blackcat/config.json' in result.content


def test_systemd_install_writes_unit_and_runs_commands(tmp_path):
    commands: list[list[str]] = []
    workspace = tmp_path / "missing-workspace"
    installer = GatewayServiceInstaller(
        platform_name="Linux",
        home=tmp_path,
        subprocess_run=lambda command, **_kwargs: commands.append(command),
    )

    result = installer.install(
        GatewayServiceOptions(
            start=GatewayStartOptions(port=18790, workspace=str(workspace)),
            enable=False,
            start_now=True,
            python_executable="/python",
        )
    )

    assert result.ok is True
    assert result.path is not None
    assert result.path.exists()
    assert workspace.exists()
    assert commands == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "restart", "blackcat-gateway.service"],
    ]


def test_launchd_install_dry_run_renders_plist(tmp_path):
    installer = GatewayServiceInstaller(platform_name="Darwin", home=tmp_path)

    result = installer.install(
        GatewayServiceOptions(
            start=GatewayStartOptions(
                port=18791,
                workspace="/Users/test/.blackcat/workspace",
                config_path="/Users/test/.blackcat/config.json",
            ),
            python_executable="/opt/homebrew/bin/python3",
        ),
        dry_run=True,
    )

    assert result.ok is True
    assert result.manager == "launchd"
    assert result.path == tmp_path / "Library/LaunchAgents/ai.blackcat.gateway.plist"
    assert result.content is not None
    payload = plistlib.loads(result.content.encode("utf-8"))
    assert payload["Label"] == "ai.blackcat.gateway"
    assert payload["ProgramArguments"] == [
        "/opt/homebrew/bin/python3",
        "-m",
        "blackcat",
        "gateway",
        "--foreground",
        "--port",
        "18791",
        "--workspace",
        "/Users/test/.blackcat/workspace",
        "--config",
        "/Users/test/.blackcat/config.json",
    ]
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["RunAtLoad"] is True
    assert ("launchctl", "bootstrap", _expected_launchd_domain(), str(result.path)) in result.commands


def test_launchd_no_enable_start_still_bootstraps(tmp_path):
    installer = GatewayServiceInstaller(platform_name="Darwin", home=tmp_path)

    result = installer.install(
        GatewayServiceOptions(
            start=GatewayStartOptions(port=18790),
            enable=False,
            start_now=True,
        ),
        dry_run=True,
    )

    assert result.content is not None
    payload = plistlib.loads(result.content.encode("utf-8"))
    assert payload["RunAtLoad"] is False
    assert result.commands[0][:2] == ("launchctl", "bootstrap")
    assert not any(command[1] == "enable" for command in result.commands)
    assert any(command[1] == "kickstart" for command in result.commands)


def test_launchd_enable_without_start_sets_run_at_load_without_bootstrap(tmp_path):
    installer = GatewayServiceInstaller(platform_name="Darwin", home=tmp_path)

    result = installer.install(
        GatewayServiceOptions(
            start=GatewayStartOptions(port=18790),
            enable=True,
            start_now=False,
        ),
        dry_run=True,
    )

    assert result.content is not None
    payload = plistlib.loads(result.content.encode("utf-8"))
    assert payload["RunAtLoad"] is True
    assert not any(command[1] == "bootstrap" for command in result.commands)
    assert any(command[1] == "enable" for command in result.commands)
    assert not any(command[1] == "kickstart" for command in result.commands)


def test_launchd_no_enable_start_reinstall_boots_out_existing_label(tmp_path):
    commands: list[list[str]] = []
    installer = GatewayServiceInstaller(
        platform_name="Darwin",
        home=tmp_path,
        subprocess_run=lambda command, **_kwargs: commands.append(command),
    )

    result = installer.install(
        GatewayServiceOptions(
            start=GatewayStartOptions(port=18790),
            enable=False,
            start_now=True,
        )
    )

    assert result.ok is True
    assert commands[0][:2] == ["launchctl", "bootout"]
    assert commands[1][:2] == ["launchctl", "bootstrap"]


def test_launchd_dry_run_does_not_require_posix_getuid(tmp_path, monkeypatch):
    monkeypatch.delattr(os, "getuid", raising=False)
    installer = GatewayServiceInstaller(platform_name="Darwin", home=tmp_path)

    result = installer.install(
        GatewayServiceOptions(start=GatewayStartOptions(port=18790)),
        dry_run=True,
    )

    assert result.ok is True
    assert result.commands[0][:3] == ("launchctl", "bootstrap", "gui/current")


def test_uninstall_systemd_removes_unit_and_reloads(tmp_path):
    commands: list[list[str]] = []
    installer = GatewayServiceInstaller(
        platform_name="Linux",
        home=tmp_path,
        subprocess_run=lambda command, **_kwargs: commands.append(command),
    )
    unit = tmp_path / ".config/systemd/user/blackcat-gateway.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("[Unit]\n", encoding="utf-8")

    result = installer.uninstall()

    assert result.ok is True
    assert not unit.exists()
    assert commands == [
        ["systemctl", "--user", "disable", "--now", "blackcat-gateway.service"],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_auto_manager_rejects_windows_services(tmp_path):
    installer = GatewayServiceInstaller(platform_name="Windows", home=tmp_path)

    result = installer.install(
        GatewayServiceOptions(start=GatewayStartOptions(port=18790)),
        dry_run=True,
    )

    assert result.ok is False
    assert result.message == "unsupported_service_manager:windows"
