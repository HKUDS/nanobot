from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
import typer
from filelock import FileLock
from typer.testing import CliRunner

from nanobot import update
from nanobot.cli.update import update as update_command
from nanobot.optional_features import install_packages
from nanobot.webui.update_service import UpdateService


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "--initial-branch=main")
    git(upstream, "config", "user.name", "Update test")
    git(upstream, "config", "user.email", "test@example.invalid")
    (upstream / "file").write_text("first", encoding="utf-8")
    git(upstream, "add", ".")
    git(upstream, "commit", "-m", "first")
    root = tmp_path / "checkout"
    git(tmp_path, "clone", str(upstream), str(root))
    monkeypatch.setattr(update, "source_checkout", lambda: root)
    return root, upstream


def test_source_update_fast_forwards_current_branch(checkout):
    root, upstream = checkout
    (upstream / "file").write_text("second", encoding="utf-8")
    git(upstream, "commit", "-am", "second")
    assert update._prepare_source(lambda _: None) == root
    assert git(root, "rev-parse", "HEAD") == git(upstream, "rev-parse", "HEAD")
    assert git(root, "branch", "--show-current") == "main"


def test_release_install_gets_a_managed_source_checkout(checkout, tmp_path, monkeypatch):
    _, upstream = checkout
    monkeypatch.setattr(update, "source_checkout", lambda: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(update, "_SOURCE_URL", str(upstream))
    root = update._prepare_source(lambda _: None)
    assert root == tmp_path / ".nanobot/src" / update._installation_key()
    assert git(root, "rev-parse", "HEAD") == git(upstream, "rev-parse", "HEAD")
    assert update._prepare_source(lambda _: None) == root


def test_source_update_preserves_local_changes(checkout):
    root, _ = checkout
    (root / "file").write_text("my edits", encoding="utf-8")
    before = git(root, "rev-parse", "HEAD")
    with pytest.raises(update.UpdateError, match="local changes"):
        update._prepare_source(lambda _: None)
    assert (root / "file").read_text() == "my edits"
    assert git(root, "rev-parse", "HEAD") == before


def test_source_update_refuses_local_commits(checkout):
    root, _ = checkout
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "--allow-empty", "-m", "local")
    before = git(root, "rev-parse", "HEAD")
    with pytest.raises(update.UpdateError, match="cannot fast-forward"):
        update._prepare_source(lambda _: None)
    assert git(root, "rev-parse", "HEAD") == before


@pytest.fixture
def isolated_update(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("RENDER", raising=False)
    if Path("/.dockerenv").exists():
        pytest.skip("Self-update intentionally refuses containers")
    monkeypatch.setattr(update, "latest_release", lambda: "0.3.5")
    monkeypatch.setattr(update, "_checked", lambda *args, **kwargs: "0.3.5")
    install = Mock()
    monkeypatch.setattr(update, "_install", install)
    return install


def test_release_update_replaces_same_version_editable_only(isolated_update, monkeypatch):
    monkeypatch.setattr(update, "_is_editable", lambda: True)
    result = update.update_installation(output=lambda _: None)
    assert result == {"version": "0.3.5", "source": "pypi", "requires_restart": True}
    assert isolated_update.call_args_list[0].args == (["nanobot-ai==0.3.5"],)
    assert isolated_update.call_args_list[1].args == (
        ["--force-reinstall", "--no-deps", "nanobot-ai==0.3.5"],
    )


def test_release_update_does_not_force_reinstall_wheel(isolated_update, monkeypatch):
    monkeypatch.setattr(update, "_is_editable", lambda: False)
    update.update_installation(output=lambda _: None)
    isolated_update.assert_called_once_with(["nanobot-ai==0.3.5"], upgrade=True)


def test_update_verifies_in_fresh_interpreter(isolated_update, monkeypatch):
    monkeypatch.setattr(update, "_is_editable", lambda: False)
    checked = Mock(return_value="old")
    monkeypatch.setattr(update, "_checked", checked)
    with pytest.raises(update.UpdateError, match="expected 0.3.5"):
        update.update_installation(output=lambda _: None)
    assert checked.call_args.args[0][:3] == [sys.executable, "-I", "-c"]


def test_update_lock_excludes_other_processes(isolated_update, tmp_path):
    lock = tmp_path / ".nanobot/run" / f"update-{update._installation_key()}.lock"
    lock.parent.mkdir(parents=True)
    with FileLock(str(lock)):
        with pytest.raises(update.UpdateError, match="already running"):
            update.update_installation()
    isolated_update.assert_not_called()


@pytest.mark.parametrize("has_uv", [False, True])
def test_installer_bootstraps_only_when_pip_is_missing(monkeypatch, has_uv):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 1, "", "No module named pip")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("nanobot.optional_features.shutil.which", lambda _: "uv" if has_uv else None)
    result = install_packages(["--force-reinstall", "--no-deps", "nanobot-ai==0.3.5"], "update", runner=run)
    assert result.ok
    if has_uv:
        assert calls[1][:5] == ["uv", "pip", "install", "--python", sys.executable]
        assert "--reinstall" in calls[1]
        assert "--force-reinstall" not in calls[1]
        assert "--no-deps" in calls[1]
    else:
        assert calls[1] == [sys.executable, "-m", "ensurepip", "--upgrade"]
        assert calls[2] == calls[0]


def test_installer_preserves_satisfied_dependencies():
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    assert install_packages(["nanobot-ai==0.3.5"], "update", upgrade=True, runner=runner).ok
    command = runner.call_args.args[0]
    assert command[:4] == [sys.executable, "-m", "pip", "install"]
    assert command[command.index("--upgrade-strategy") + 1] == "only-if-needed"
    assert "--force-reinstall" not in command


@pytest.mark.asyncio
async def test_web_update_survives_readers_and_rejects_duplicates(monkeypatch):
    release = threading.Event()

    def install(*, dev, output):
        assert dev is True
        output("Building WebUI")
        assert release.wait(5)
        return {"version": "0.3.5", "source": "test", "requires_restart": True}

    monkeypatch.setattr("nanobot.webui.update_service.update_installation", install)
    service = UpdateService()
    try:
        assert service.start(dev=True)["state"] == "running"
        with pytest.raises(update.UpdateError, match="already running"):
            service.start(dev=False)
        snapshot = service.status()
        snapshot["message"] = "client edit"
        assert service.status()["message"] != "client edit"
    finally:
        release.set()
        await service.close()
    assert service.status()["state"] == "succeeded"
    assert service.status()["requires_restart"] is True


@pytest.mark.asyncio
async def test_web_update_reports_failure_and_allows_retry(monkeypatch):
    monkeypatch.setattr("nanobot.webui.update_service.update_installation", Mock(side_effect=update.UpdateError("offline")))
    service = UpdateService()
    for _ in range(2):
        service.start(dev=False)
        await service.close()
        assert service.status()["state"] == "failed"
        assert service.status()["message"] == "offline"
        assert service.status()["requires_restart"] is False


def test_cli_check_is_read_only(monkeypatch):
    monkeypatch.setattr(update, "latest_release", lambda: "9.0.0")
    install = Mock()
    monkeypatch.setattr(update, "update_installation", install)
    app = typer.Typer()
    app.command()(update_command)
    result = CliRunner().invoke(app, ["--check"])
    assert result.exit_code == 0
    assert "Latest release: 9.0.0" in result.stdout
    install.assert_not_called()


def test_windows_launchers_are_replaced_without_overwriting_running_file(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(update.sysconfig, "get_path", lambda _: str(tmp_path))
    launcher = tmp_path / "nanobot.exe"
    launcher.write_bytes(b"old")
    with update._release_windows_launchers():
        assert not launcher.exists()
        assert (tmp_path / ".nanobot.exe.update-backup").read_bytes() == b"old"
        launcher.write_bytes(b"new")
    assert launcher.read_bytes() == b"new"
    assert not (tmp_path / ".nanobot.exe.update-backup").exists()


def test_windows_launchers_are_restored_after_failed_or_noop_install(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(update.sysconfig, "get_path", lambda _: str(tmp_path))
    launcher = tmp_path / "nanobot.exe"
    launcher.write_bytes(b"old")
    with pytest.raises(update.UpdateError):
        with update._release_windows_launchers():
            raise update.UpdateError("offline")
    assert launcher.read_bytes() == b"old"


def test_windows_recovers_launcher_left_by_interrupted_update(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(update.sysconfig, "get_path", lambda _: str(tmp_path))
    (tmp_path / ".nanobot.exe.update-backup").write_bytes(b"old")
    with update._release_windows_launchers():
        pass
    assert (tmp_path / "nanobot.exe").read_bytes() == b"old"


@pytest.mark.parametrize("flag", ["--dev", "--update-dev"])
def test_cli_dev_is_explicit(monkeypatch, flag):
    install = Mock(return_value={"version": "0.3.5"})
    monkeypatch.setattr(update, "update_installation", install)
    app = typer.Typer()
    app.command()(update_command)
    assert CliRunner().invoke(app, [flag]).exit_code == 0
    assert install.call_args.kwargs["dev"] is True
