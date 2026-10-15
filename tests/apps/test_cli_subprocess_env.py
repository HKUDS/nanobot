"""CLI app subprocesses must not inherit API keys from the parent environ."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from nanobot.apps.cli.service import CliAppManager


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("runtime_dir", ["/run/user/1000", None])
def test_subprocess_env_excludes_api_keys(monkeypatch, tmp_path, platform, runtime_dir) -> None:
    monkeypatch.setattr("nanobot.apps.cli.service.sys.platform", platform)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-leak")
    if runtime_dir is None:
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    else:
        monkeypatch.setenv("XDG_RUNTIME_DIR", runtime_dir)

    manager = CliAppManager(workspace=tmp_path, data_dir=tmp_path / "cli-apps")
    env = manager._subprocess_env()

    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENROUTER_API_KEY" not in env
    assert env.get("PYTHONUNBUFFERED") == "1"
    assert "PATH" in env
    assert env.get("XDG_RUNTIME_DIR") == runtime_dir
    if runtime_dir is None:
        assert "XDG_RUNTIME_DIR" not in env


def test_subprocess_env_excludes_api_keys_on_windows(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.apps.cli.service.sys.platform", "win32")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")

    manager = CliAppManager(workspace=tmp_path, data_dir=tmp_path / "cli-apps")
    env = manager._subprocess_env()

    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["SYSTEMROOT"]
    assert "XDG_RUNTIME_DIR" not in env
    assert all(isinstance(value, str) for value in env.values())


def test_run_passes_filtered_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    manager = CliAppManager(workspace=tmp_path, data_dir=tmp_path / "cli-apps")
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr("nanobot.apps.cli.service.subprocess.run", fake_run)
    monkeypatch.setattr(manager, "get_app", lambda name: {"name": name, "entry_point": "echo"})
    monkeypatch.setattr(
        manager,
        "_load_installed",
        lambda: {"echo": {"entry_point": "echo"}},
    )
    monkeypatch.setattr("nanobot.apps.cli.service.shutil.which", lambda entry: "/bin/echo")
    monkeypatch.setattr(manager, "_resolve_cwd", lambda *a, **k: tmp_path)
    monkeypatch.setattr(manager, "_artifact_snapshot", lambda cwd: {})
    monkeypatch.setattr(manager, "_changed_artifacts", lambda cwd, snap: [])

    manager.run("echo", ["hi"])

    env = captured.get("env")
    assert isinstance(env, dict)
    assert "OPENAI_API_KEY" not in env


def test_management_subprocesses_use_filtered_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    monkeypatch.setattr("nanobot.apps.cli.service.subprocess.run", fake_run)
    manager = CliAppManager(workspace=tmp_path, data_dir=tmp_path / "cli-apps")

    manager._run_argv(["example-cli", "--help"], timeout=5)

    env = captured.get("env")
    assert isinstance(env, dict)
    assert "OPENAI_API_KEY" not in env
    assert env["PYTHONUNBUFFERED"] == "1"


@pytest.mark.parametrize("operation", ["run", "management"])
@pytest.mark.parametrize("runtime_dir", ["/run/user/1000", None])
def test_child_process_receives_runtime_dir_without_api_keys(
    monkeypatch, tmp_path, operation, runtime_dir,
) -> None:
    secrets = {
        "OPENAI_API_KEY": "cli-env-openai-sentinel",
        "ANTHROPIC_API_KEY": "cli-env-anthropic-sentinel",
        "OPENROUTER_API_KEY": "cli-env-openrouter-sentinel",
    }
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)
    if runtime_dir is None:
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    else:
        monkeypatch.setenv("XDG_RUNTIME_DIR", runtime_dir)

    manager = CliAppManager(workspace=tmp_path, data_dir=tmp_path / "cli-apps")
    manager._save_installed({"env-check": {"entry_point": sys.executable}})
    monkeypatch.setattr(manager, "get_app", lambda name: {"name": name})
    keys = ("XDG_RUNTIME_DIR", *secrets)
    args = [
        "-c",
        "import json, os; print(json.dumps({key: os.environ.get(key) "
        f"for key in {keys!r}}}))",
    ]
    if operation == "run":
        output = manager.run("env-check", args)
        assert "exited 0" in output
    else:
        result = manager._run_argv([sys.executable, *args], timeout=5)
        assert result.returncode == 0
        output = result.stdout

    expected = {key: None for key in keys}
    expected["XDG_RUNTIME_DIR"] = runtime_dir if sys.platform != "win32" else None
    assert json.dumps(expected) in output
    assert all(value not in output for value in secrets.values())
