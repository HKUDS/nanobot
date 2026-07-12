import json
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from nanobot.gateway import GatewayRuntime, GatewayRuntimePaths, GatewayStartOptions, GatewayStatus


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

    def fake_terminate(pid, timeout_s):
        terminated.append(pid)
        return True

    monkeypatch.setattr(runtime, "_terminate", fake_terminate)

    result = runtime.stop()

    assert result.ok is True
    assert terminated == [12345]
    assert not runtime.paths.state_path.exists()


def test_stop_keeps_state_when_process_survives_timeout(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    runtime.paths.run_dir.mkdir(parents=True)
    runtime.paths.state_path.write_text('{"pid": 12345, "identity": 12345}', encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 12345)
    monkeypatch.setattr(runtime, "_terminate", lambda _pid, timeout_s: False)

    result = runtime.stop(timeout_s=0)

    assert result.ok is False
    assert result.message == "gateway_stop_timeout"
    assert result.status.running is True
    assert result.status.reason == "stop_timeout"
    assert runtime.paths.state_path.exists()


def test_stop_succeeds_when_process_exits_at_timeout_boundary(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    running = GatewayStatus(
        running=True,
        pid=12345,
        state_path=runtime.paths.state_path,
        log_path=runtime.paths.log_path,
    )
    stopped = GatewayStatus(
        running=False,
        pid=None,
        state_path=runtime.paths.state_path,
        log_path=runtime.paths.log_path,
        reason="stop_timeout",
    )
    statuses = iter([running, stopped])
    monkeypatch.setattr(runtime, "status", lambda **_kwargs: next(statuses))
    monkeypatch.setattr(runtime, "_read_state", lambda: {"pid": 12345, "identity": 12345})
    monkeypatch.setattr(runtime, "_record_matches_process", lambda *_args: True)
    monkeypatch.setattr(runtime, "_terminate", lambda *_args, **_kwargs: False)

    result = runtime.stop(timeout_s=0)

    assert result.ok is True
    assert result.message == "gateway_stopped"
    assert result.status.running is False


def test_terminate_windows_falls_back_when_ctrl_break_is_rejected(tmp_path, monkeypatch):
    taskkill_calls: list[dict] = []
    wait_timeouts: list[int | float] = []

    def fake_run(command, **kwargs):
        taskkill_calls.append({"command": command, "kwargs": kwargs})

    runtime = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Windows",
        subprocess_run=fake_run,
        sleep=lambda _seconds: None,
    )

    monkeypatch.setattr(signal, "CTRL_BREAK_EVENT", 1, raising=False)

    def fake_kill(_pid, _signal):
        raise OSError(87, "The parameter is incorrect")

    monkeypatch.setattr("nanobot.process_runtime.os.kill", fake_kill)

    def fake_wait_for_exit(_pid, _timeout_s):
        wait_timeouts.append(_timeout_s)
        # Simulate a process that only exits after the taskkill fallback runs.
        return bool(taskkill_calls)

    monkeypatch.setattr(runtime, "_wait_for_exit", fake_wait_for_exit)

    assert runtime._terminate_windows(12345, timeout_s=20) is True
    assert wait_timeouts == [2]
    assert taskkill_calls == [
        {
            "command": ["taskkill", "/PID", "12345", "/T"],
            "kwargs": {
                "check": False,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            },
        }
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups are unavailable")
def test_terminate_posix_tolerates_process_group_disappearing_before_sigkill(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Darwin",
        sleep=lambda _seconds: None,
    )
    waits = iter([False, True])
    monkeypatch.setattr(
        "nanobot.process_runtime.os.getpgid",
        lambda _pid: 1234,
        raising=False,
    )

    def fake_killpg(_pgid, sent_signal):
        if sent_signal == signal.SIGKILL:
            raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("nanobot.process_runtime.os.killpg", fake_killpg, raising=False)
    monkeypatch.setattr(runtime, "_wait_for_exit", lambda *_args: next(waits))

    assert runtime._terminate_posix(1234, timeout_s=1) is True
