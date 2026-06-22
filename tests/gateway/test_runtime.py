import json
from pathlib import Path

from nanobot.gateway import GatewayRuntime, GatewayRuntimePaths, GatewayStartOptions


class FakeProcess:
    def __init__(self, pid: int = 12345):
        self.pid = pid


def _paths(tmp_path: Path) -> GatewayRuntimePaths:
    return GatewayRuntimePaths.for_instance(data_dir=tmp_path)


def test_paths_use_stable_instance_suffix_for_custom_selectors(tmp_path):
    default_paths = GatewayRuntimePaths.for_instance(data_dir=tmp_path)
    first_paths = GatewayRuntimePaths.for_instance(
        data_dir=tmp_path,
        workspace="/tmp/workspace-a",
        config_path="/tmp/config-a.json",
    )
    second_paths = GatewayRuntimePaths.for_instance(
        data_dir=tmp_path,
        workspace="/tmp/workspace-b",
        config_path="/tmp/config-b.json",
    )

    assert default_paths.state_path.name == "gateway.json"
    assert first_paths.state_path.name.startswith("gateway.")
    assert first_paths.state_path != second_paths.state_path
    assert first_paths.log_path != second_paths.log_path


def test_start_background_writes_state_and_child_command(tmp_path, monkeypatch):
    calls: list[dict] = []

    def fake_popen(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        return FakeProcess()

    runtime = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Linux",
        python_executable="/python",
        popen=fake_popen,
        sleep=lambda _seconds: None,
    )
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 12345)

    result = runtime.start_background(
        GatewayStartOptions(
            port=18790,
            verbose=True,
            workspace="/tmp/workspace",
            config_path="/tmp/config.json",
        )
    )

    assert result.ok is True
    assert result.status.running is True
    assert calls[0]["command"] == [
        "/python",
        "-m",
        "nanobot",
        "gateway",
        "--foreground",
        "--port",
        "18790",
        "--verbose",
        "--workspace",
        "/tmp/workspace",
        "--config",
        "/tmp/config.json",
    ]
    assert calls[0]["kwargs"]["start_new_session"] is True
    state = json.loads(runtime.paths.state_path.read_text(encoding="utf-8"))
    assert state["pid"] == 12345
    assert state["identity"] == 12345
    assert state["port"] == 18790


def test_start_background_uses_windows_process_group_flags(tmp_path, monkeypatch):
    calls: list[dict] = []

    def fake_popen(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        return FakeProcess()

    runtime = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Windows",
        python_executable="python.exe",
        popen=fake_popen,
        sleep=lambda _seconds: None,
    )
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: "created-at")

    result = runtime.start_background(GatewayStartOptions(port=18790))

    assert result.ok is True
    assert "creationflags" in calls[0]["kwargs"]
    assert "start_new_session" not in calls[0]["kwargs"]


def test_status_clears_stale_state(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    runtime.paths.run_dir.mkdir(parents=True)
    runtime.paths.state_path.write_text('{"pid": 12345, "identity": 12345}', encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: False)

    status = runtime.status()

    assert status.running is False
    assert status.reason == "stale_state"
    assert not runtime.paths.state_path.exists()


def test_status_clears_state_when_pid_identity_changes(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    runtime.paths.run_dir.mkdir(parents=True)
    runtime.paths.state_path.write_text('{"pid": 12345, "identity": 111}', encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 222)

    status = runtime.status()

    assert status.running is False
    assert status.reason == "stale_state"
    assert not runtime.paths.state_path.exists()


def test_stop_terminates_recorded_process(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    runtime.paths.run_dir.mkdir(parents=True)
    runtime.paths.state_path.write_text('{"pid": 12345, "identity": 12345}', encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 12345)
    terminated: list[int] = []
    monkeypatch.setattr(runtime, "_terminate", lambda pid, timeout_s: terminated.append(pid))

    result = runtime.stop()

    assert result.ok is True
    assert terminated == [12345]
    assert not runtime.paths.state_path.exists()
