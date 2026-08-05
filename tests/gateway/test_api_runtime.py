from pathlib import Path

from nanobot.api.runtime import ApiRuntime, ApiStartOptions, api_runtime_paths, probe_api_health


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


class FakeHealthResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "FakeHealthResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_probe_api_health_success(monkeypatch) -> None:
    def fake_urlopen(url, **kwargs):
        assert url == "http://127.0.0.1:9900/health"
        assert kwargs["timeout"] == 0.25
        return FakeHealthResponse(200)

    monkeypatch.setattr("nanobot.api.runtime.urlopen", fake_urlopen)
    assert probe_api_health("127.0.0.1", 9900, timeout=0.25) is True


def test_probe_api_health_rejects_other_responses(monkeypatch) -> None:
    def fake_urlopen(_url, **_kwargs):
        return FakeHealthResponse(404)

    monkeypatch.setattr("nanobot.api.runtime.urlopen", fake_urlopen)
    assert probe_api_health("127.0.0.1", 9900) is False


def test_probe_api_health_swallows_errors(monkeypatch) -> None:
    def fake_urlopen(_url, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("nanobot.api.runtime.urlopen", fake_urlopen)
    assert probe_api_health("127.0.0.1", 9900) is False


def test_effective_status_detects_external_server(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.api.runtime.probe_api_health", lambda _host, _port, **kwargs: True)
    runtime = ApiRuntime(paths=api_runtime_paths(tmp_path / "config.json"))

    status = runtime.effective_status(host="127.0.0.1", port=9900)

    assert status.running is True
    assert status.managed is False
    assert status.pid is None
    assert status.port == 9900
    assert status.reason == "external"


def test_effective_status_reports_off_without_server(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.api.runtime.probe_api_health", lambda _host, _port, **kwargs: False)
    runtime = ApiRuntime(paths=api_runtime_paths(tmp_path / "config.json"))

    status = runtime.effective_status(host="127.0.0.1", port=9900)

    assert status.running is False
    assert status.managed is False
    assert status.reason == "not_started"


def test_effective_status_keeps_managed_running(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "nanobot.api.runtime.probe_api_health",
        lambda _host, _port, **kwargs: (_ for _ in ()).throw(AssertionError("probe must not run")),
    )
    runtime = ApiRuntime(
        paths=api_runtime_paths(tmp_path / "config.json"),
        platform_name="Linux",
        python_executable="/python",
        popen=lambda *_args, **_kwargs: FakeProcess(),
        sleep=lambda _seconds: None,
    )
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 23456)

    started = runtime.start_background(ApiStartOptions(host="127.0.0.1", port=9900))
    assert started.ok is True

    status = runtime.effective_status(host="127.0.0.1", port=9900)

    assert status.running is True
    assert status.managed is True
    assert status.pid == 23456
    assert status.reason == "running"
