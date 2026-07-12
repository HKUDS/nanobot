from pathlib import Path

from nanobot.api.runtime import ApiRuntime, ApiStartOptions, api_runtime_paths


class FakeProcess:
    pid = 23456


def test_api_runtime_uses_isolated_paths(tmp_path: Path) -> None:
    paths = api_runtime_paths(tmp_path / "config.json")

    assert paths.state_path.parent == tmp_path / "run"
    assert paths.state_path.name.startswith("api.")
    assert paths.log_path.parent == tmp_path / "logs"


def test_api_runtime_builds_detached_serve_command(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_popen(command, **_kwargs):
        calls.append(command)
        return FakeProcess()

    runtime = ApiRuntime(
        paths=api_runtime_paths(tmp_path / "config.json"),
        platform_name="Linux",
        python_executable="/python",
        popen=fake_popen,
        sleep=lambda _seconds: None,
    )
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 23456)

    result = runtime.start_background(ApiStartOptions(
        host="0.0.0.0",
        port=9900,
        workspace="/tmp/workspace",
        config_path="/tmp/config.json",
    ))

    assert result.ok is True
    assert result.message == "api_started_background"
    assert calls == [[
        "/python",
        "-m",
        "nanobot",
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "9900",
        "--workspace",
        "/tmp/workspace",
        "--config",
        "/tmp/config.json",
    ]]
