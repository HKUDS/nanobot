"""CLI app subprocesses must not inherit API keys from the parent environ."""

from __future__ import annotations

import subprocess

from nanobot.apps.cli.service import CliAppManager


def test_subprocess_env_excludes_api_keys(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-leak")

    manager = CliAppManager(workspace=tmp_path, data_dir=tmp_path / "cli-apps")
    env = manager._subprocess_env()

    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENROUTER_API_KEY" not in env
    assert env.get("PYTHONUNBUFFERED") == "1"
    assert "PATH" in env


def test_subprocess_env_excludes_api_keys_on_windows(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.apps.cli.service.sys.platform", "win32")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak")

    manager = CliAppManager(workspace=tmp_path, data_dir=tmp_path / "cli-apps")
    env = manager._subprocess_env()

    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["SYSTEMROOT"]
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
