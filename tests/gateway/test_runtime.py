import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.gateway import (
    GatewayClientLease,
    GatewayRuntime,
    GatewayRuntimePaths,
    GatewayStartOptions,
    GatewayStatus,
)
from nanobot.gateway.runtime import monitor_gateway_clients
from nanobot.process_runtime import process_is_running


class FakeProcess:
    def __init__(self, pid: int = 12345):
        self.pid = pid


class PollableProcess(FakeProcess):
    def __init__(self, pid: int = 12345):
        super().__init__(pid)
        self.returncode: int | None = None

    def poll(self):
        return self.returncode


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
    assert state["launch_mode"] == "background"
    assert result.status.launch_mode == "background"


def test_foreground_gateway_claim_is_discoverable_and_released(tmp_path, monkeypatch):
    runtime = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Darwin",
        python_executable="/python",
    )
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 54321)
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    options = GatewayStartOptions(
        port=18790,
        workspace="/tmp/workspace",
        config_path="/tmp/config.json",
    )

    with runtime.foreground_instance(options):
        status = runtime.status()
        assert status.running is True
        assert status.pid == os.getpid()
        assert status.port == 18790
        assert status.launch_mode == "foreground"
        assert status.lifetime == "explicit"
        assert status.command == tuple(runtime._build_child_command(options))

    assert runtime.status().running is False
    assert not runtime.paths.state_path.exists()


def test_explicit_foreground_gateway_clears_stale_auto_stop_state(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Darwin")
    monkeypatch.setattr(runtime, "_process_identity", lambda pid: pid)
    lease = GatewayClientLease(runtime, kind="stale")
    lease.mark_ephemeral()

    with runtime.foreground_instance(GatewayStartOptions(port=18790)):
        assert runtime.status().lifetime == "explicit"

    assert not lease.state_path.exists()


def test_foreground_gateway_release_preserves_a_replacement_state(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Darwin")
    monkeypatch.setattr(runtime, "_process_identity", lambda pid: pid)
    with runtime.foreground_instance(GatewayStartOptions(port=18790)):
        replacement = json.loads(runtime.paths.state_path.read_text(encoding="utf-8"))
        replacement["pid"] = os.getpid() + 1
        replacement["identity"] = replacement["pid"]
        runtime.paths.state_path.write_text(json.dumps(replacement), encoding="utf-8")

    assert runtime.paths.state_path.exists()


def test_foreground_gateway_clears_its_state_after_an_error(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Darwin")
    monkeypatch.setattr(runtime, "_process_identity", lambda pid: pid)

    with pytest.raises(RuntimeError, match="startup failed"):
        with runtime.foreground_instance(GatewayStartOptions(port=18790)):
            raise RuntimeError("startup failed")

    assert not runtime.paths.state_path.exists()


def test_stop_reaps_an_owned_child_without_consuming_the_shutdown_timeout(
    tmp_path,
    monkeypatch,
):
    process = PollableProcess()
    sleeps: list[float] = []
    runtime = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Darwin",
        popen=lambda *_args, **_kwargs: process,
        sleep=sleeps.append,
    )
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 12345)
    monkeypatch.setattr(
        "nanobot.process_runtime.os.getpgid",
        lambda _pid: process.pid,
        raising=False,
    )
    monkeypatch.setattr(
        "nanobot.process_runtime.os.killpg",
        lambda _pgid, _signal: setattr(process, "returncode", -15),
        raising=False,
    )

    assert runtime.start_background(GatewayStartOptions(port=18790)).ok is True
    sleeps.clear()
    result = runtime.stop(timeout_s=20)

    assert result.ok is True
    assert sleeps == []


def test_repeated_background_starts_create_only_one_process(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_popen(command, **_kwargs):
        calls.append(command)
        return FakeProcess()

    first = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Linux",
        popen=fake_popen,
        sleep=lambda _seconds: None,
    )
    second = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Linux",
        popen=fake_popen,
        sleep=lambda _seconds: None,
    )
    for runtime in (first, second):
        monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
        monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 12345)

    results = [
        first.start_background(GatewayStartOptions(port=18790)),
        second.start_background(GatewayStartOptions(port=18790)),
    ]

    assert len(calls) == 1
    assert sorted((result.ok, result.message) for result in results) == [
        (False, "gateway_already_running"),
        (True, "gateway_started_background"),
    ]


def test_restart_does_not_start_a_gateway_that_is_not_running(tmp_path):
    spawned: list[list[str]] = []
    runtime = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Linux",
        popen=lambda command, **_kwargs: spawned.append(command),
    )

    result = runtime.restart(GatewayStartOptions(port=18790))

    assert result.ok is False
    assert result.message == "gateway_not_running"
    assert spawned == []


def test_restart_does_not_detach_a_foreground_gateway(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    status = GatewayStatus(
        running=True,
        pid=12345,
        state_path=runtime.paths.state_path,
        log_path=runtime.paths.log_path,
        launch_mode="foreground",
    )
    monkeypatch.setattr(runtime, "status", lambda **_kwargs: status)
    monkeypatch.setattr(
        runtime,
        "_stop",
        lambda **_kwargs: pytest.fail("foreground gateway must not be stopped"),
    )

    result = runtime.restart(GatewayStartOptions(port=18790))

    assert result.ok is False
    assert result.message == "gateway_foreground_restart_required"


def test_last_interactive_client_stops_an_on_demand_gateway(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    monkeypatch.setattr(runtime, "_process_identity", lambda pid: pid)
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    stopped: list[int] = []

    def stop(*, timeout_s: int):
        stopped.append(timeout_s)
        return SimpleNamespace(ok=True, message="gateway_stopped")

    monkeypatch.setattr(runtime, "stop", stop)
    tui = GatewayClientLease(runtime, kind="tui", pid=os.getpid(), token="tui")
    webui = GatewayClientLease(runtime, kind="webui", pid=os.getpid(), token="webui")

    tui.acquire()
    tui.mark_ephemeral()
    webui.acquire()

    assert tui.release() is False
    assert stopped == []
    assert webui.release() is True
    assert stopped == [20]
    assert not webui.state_path.exists()


def test_on_demand_lifetime_is_recorded_before_the_gateway_spawns(tmp_path, monkeypatch):
    observed_auto_stop: list[bool] = []

    def fake_popen(*_args, **_kwargs):
        lease_path = runtime.paths.state_path.with_name("gateway.clients.json")
        observed_auto_stop.append(
            json.loads(lease_path.read_text(encoding="utf-8"))["auto_stop"]
        )
        return FakeProcess()

    runtime = GatewayRuntime(
        paths=_paths(tmp_path),
        platform_name="Linux",
        popen=fake_popen,
        sleep=lambda _seconds: None,
    )
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 12345)
    client = GatewayClientLease(runtime, kind="tui", token="client")
    client.acquire()

    result = client.ensure_on_demand_gateway(GatewayStartOptions(port=18790))

    assert result.ok is True
    assert observed_auto_stop == [True]
    assert result.status.lifetime == "on_demand"


def test_explicit_background_gateway_survives_the_last_client(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    monkeypatch.setattr(runtime, "_process_identity", lambda pid: pid)
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    stopped: list[int] = []
    monkeypatch.setattr(
        runtime,
        "stop",
        lambda *, timeout_s: stopped.append(timeout_s),
    )
    client = GatewayClientLease(runtime, kind="webui", pid=os.getpid())

    client.acquire()
    client.mark_ephemeral()
    assert GatewayClientLease(runtime, kind="gateway-background").mark_persistent() is True

    assert client.release() is False
    assert stopped == []
    assert not client.state_path.exists()


def test_failed_last_client_shutdown_remains_retryable(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    monkeypatch.setattr(runtime, "_process_identity", lambda pid: pid)
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(
        runtime,
        "stop",
        lambda *, timeout_s: SimpleNamespace(ok=False, message="gateway_stop_timeout"),
    )
    client = GatewayClientLease(runtime, kind="tui", pid=os.getpid())
    client.acquire()
    client.mark_ephemeral()

    assert client.release() is False
    state = json.loads(client.state_path.read_text(encoding="utf-8"))
    assert state == {"auto_stop": True, "clients": {}}


def test_lease_snapshot_prunes_a_reused_client_pid(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    identity = "same-pid:first-process"
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: identity)
    client = GatewayClientLease(runtime, kind="tui", pid=12345, token="client")

    client.acquire()
    client.mark_ephemeral()
    identity = "same-pid:replacement-process"

    snapshot = client.snapshot()
    assert snapshot.auto_stop is True
    assert snapshot.clients == 0
    assert json.loads(client.state_path.read_text(encoding="utf-8")) == {
        "auto_stop": True,
        "clients": {},
    }


async def test_client_monitor_stops_an_orphaned_on_demand_gateway(tmp_path):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    lease = GatewayClientLease(runtime, kind="gateway-monitor")
    lease.mark_ephemeral()
    shutdown_event = asyncio.Event()

    orphaned = await monitor_gateway_clients(
        lease,
        shutdown_event,
        poll_interval_s=0.001,
    )

    assert orphaned is True
    assert shutdown_event.is_set()


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


def test_windows_process_probe_never_sends_ctrl_c(monkeypatch):
    monkeypatch.setattr(
        "nanobot.process_runtime._windows_process_identity",
        lambda pid: "created-at" if pid == 12345 else None,
    )
    monkeypatch.setattr(
        "nanobot.process_runtime.os.kill",
        lambda *_args: pytest.fail("Windows process probes must not call os.kill(pid, 0)"),
    )

    assert process_is_running(12345, platform_name="Windows") is True
    assert process_is_running(54321, platform_name="Windows") is False


def test_windows_host_probe_stays_safe_when_target_platform_is_posix(monkeypatch):
    monkeypatch.setattr("nanobot.process_runtime._platform_name", lambda: "Windows")
    monkeypatch.setattr(
        "nanobot.process_runtime._windows_process_identity",
        lambda pid: "created-at" if pid == 12345 else None,
    )
    monkeypatch.setattr(
        "nanobot.process_runtime.os.kill",
        lambda *_args: pytest.fail("Windows process probes must not call os.kill(pid, 0)"),
    )

    assert process_is_running(12345, platform_name="Linux") is True
    assert process_is_running(54321, platform_name="Darwin") is False


def test_windows_host_identity_stays_safe_when_target_platform_is_posix(tmp_path, monkeypatch):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    monkeypatch.setattr("nanobot.process_runtime._platform_name", lambda: "Windows")
    monkeypatch.setattr(
        "nanobot.process_runtime._windows_process_identity",
        lambda pid: "created-at" if pid == 12345 else None,
    )
    monkeypatch.setattr(
        "nanobot.process_runtime.os.getpgid",
        lambda *_args: pytest.fail("Windows process identities must not use POSIX APIs"),
        raising=False,
    )

    assert runtime.process_identity(12345) == "created-at"


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


def test_posix_process_identity_includes_start_time_and_accepts_legacy_state(
    tmp_path,
    monkeypatch,
):
    runtime = GatewayRuntime(paths=_paths(tmp_path), platform_name="Linux")
    monkeypatch.setattr("nanobot.process_runtime.os.getpgid", lambda _pid: 42, raising=False)
    monkeypatch.setattr(runtime, "_posix_process_started_at", lambda _pid: "987654")

    assert runtime.process_identity(12345) == "42:987654"
    assert runtime._record_matches_process({"identity": 42}, 12345) is True


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


def test_terminate_windows_targets_only_the_recorded_process_tree(tmp_path, monkeypatch):
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

    monkeypatch.setattr(
        "nanobot.process_runtime.os.kill",
        lambda *_args: pytest.fail("Windows termination must not broadcast a console event"),
    )

    def fake_wait_for_exit(_pid, _timeout_s):
        wait_timeouts.append(_timeout_s)
        # Simulate a process that only exits after the taskkill fallback runs.
        return bool(taskkill_calls)

    monkeypatch.setattr(runtime, "_wait_for_exit", fake_wait_for_exit)

    assert runtime._terminate_windows(12345, timeout_s=20) is True
    assert wait_timeouts == [20]
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
