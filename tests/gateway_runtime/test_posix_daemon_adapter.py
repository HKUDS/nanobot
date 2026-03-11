import signal
import subprocess

import pytest

from nanobot.gateway_runtime.models import (
    GatewayStartOptions,
    RuntimeMode,
    RuntimePolicy,
    StartResult,
    StopResult,
)
from nanobot.gateway_runtime.state_store import GatewayStateStore


def _background_policy() -> RuntimePolicy:
    return RuntimePolicy(
        mode=RuntimeMode.BACKGROUND_MANAGED,
        reason="rollout_default_on",
        platform="Darwin",
        rollout_stage="default_on",
    )


def test_start_spawns_background_child_and_persists_runtime_files(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    captured: dict[str, object] = {}

    class _Process:
        pid = 2468

    def fake_popen(
        cmd: list[str],
        *,
        stdout,
        stderr,
        start_new_session: bool,
    ):
        captured["cmd"] = cmd
        captured["stderr"] = stderr
        captured["start_new_session"] = start_new_session
        captured["stdout_name"] = getattr(stdout, "name", "")
        return _Process()

    adapter = PosixDaemonAdapter(
        policy=_background_policy(),
        state_store=store,
        python_executable="/mock/python",
        popen_factory=fake_popen,
    )
    monkeypatch.setattr(adapter, "_wait_for_stable_start", lambda _pid, timeout_s: True, raising=False)

    result = adapter.start(GatewayStartOptions(port=19090, verbose=True))

    assert result.started is True
    assert result.mode is RuntimeMode.BACKGROUND_MANAGED
    assert captured["cmd"] == [
        "/mock/python",
        "-m",
        "nanobot",
        "gateway",
        "--foreground",
        "--runtime-child",
        "--port",
        "19090",
        "--verbose",
    ]
    assert captured["stderr"] is subprocess.STDOUT
    assert captured["start_new_session"] is True

    state = store.read_state()
    assert state is not None
    assert state["mode"] == RuntimeMode.BACKGROUND_MANAGED.value
    assert state["pid"] == 2468
    assert store.read_pid() == 2468
    assert store.resolve_log_path().exists()


def test_start_passes_workspace_and_config_to_child_command(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    captured: dict[str, object] = {}

    class _Process:
        pid = 1357

    def fake_popen(
        cmd: list[str],
        *,
        stdout,
        stderr,
        start_new_session: bool,
    ):
        captured["cmd"] = cmd
        return _Process()

    adapter = PosixDaemonAdapter(
        policy=_background_policy(),
        state_store=store,
        python_executable="/mock/python",
        popen_factory=fake_popen,
    )
    monkeypatch.setattr(adapter, "_wait_for_stable_start", lambda _pid, timeout_s: True, raising=False)

    result = adapter.start(
        GatewayStartOptions(
            port=19191,
            workspace="/tmp/work-z",
            config_path="/tmp/cfg-z.json",
        )
    )

    assert result.started is True
    assert captured["cmd"] == [
        "/mock/python",
        "-m",
        "nanobot",
        "gateway",
        "--foreground",
        "--runtime-child",
        "--port",
        "19191",
        "--workspace",
        "/tmp/work-z",
        "--config",
        "/tmp/cfg-z.json",
    ]


def test_status_detects_alive_and_stale_process(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(2468)
    store.write_state({"mode": RuntimeMode.BACKGROUND_MANAGED.value, "started_at": "t1"})

    adapter = PosixDaemonAdapter(policy=_background_policy(), state_store=store)

    monkeypatch.setattr(adapter, "_is_pid_running", lambda _pid: True)
    alive = adapter.status()
    assert alive.running is True
    assert alive.pid == 2468

    monkeypatch.setattr(adapter, "_is_pid_running", lambda _pid: False)
    stale = adapter.status()
    assert stale.running is False
    assert stale.pid is None
    assert store.read_pid() is None


def test_stop_escalates_to_sigkill_after_timeout(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(3579)
    adapter = PosixDaemonAdapter(policy=_background_policy(), state_store=store)

    kill_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))

    monkeypatch.setattr("nanobot.gateway_runtime.adapters.posix_daemon.os.kill", fake_kill)
    monkeypatch.setattr(adapter, "_wait_for_exit", lambda _pid, _timeout_s: False)

    result = adapter.stop(timeout_s=1)

    assert result.stopped is True
    assert result.mode is RuntimeMode.BACKGROUND_MANAGED
    assert kill_calls[-2:] == [
        (3579, signal.SIGTERM),
        (3579, signal.SIGKILL),
    ]
    assert store.read_pid() is None


def test_restart_performs_stop_then_start(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter

    adapter = PosixDaemonAdapter(
        policy=_background_policy(),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )
    calls: list[str] = []

    def fake_stop(timeout_s: int = 20) -> StopResult:
        calls.append(f"stop:{timeout_s}")
        return StopResult(
            stopped=True,
            message="gateway_stopped_background_managed",
            mode=RuntimeMode.BACKGROUND_MANAGED,
        )

    def fake_start(_options: GatewayStartOptions) -> StartResult:
        calls.append("start")
        return StartResult(
            started=True,
            message="gateway_started_background_managed",
            mode=RuntimeMode.BACKGROUND_MANAGED,
        )

    monkeypatch.setattr(adapter, "stop", fake_stop)
    monkeypatch.setattr(adapter, "start", fake_start)

    result = adapter.restart(GatewayStartOptions(port=18888), timeout_s=9)

    assert result.restarted is True
    assert result.mode is RuntimeMode.BACKGROUND_MANAGED
    assert calls == ["stop:9", "start"]


def test_logs_reads_gateway_log_file(tmp_path, capsys) -> None:
    from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    log_path = store.resolve_log_path()
    log_path.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
    adapter = PosixDaemonAdapter(policy=_background_policy(), state_store=store)

    code = adapter.logs(follow=False, tail=2)

    out = capsys.readouterr().out
    assert code == 0
    assert "line4" in out
    assert "line3" in out
    assert "line2" not in out


def test_logs_follow_keeps_waiting_when_file_is_initially_empty(tmp_path, monkeypatch, capsys) -> None:
    from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.resolve_log_path().write_text("", encoding="utf-8")
    adapter = PosixDaemonAdapter(policy=_background_policy(), state_store=store)

    monkeypatch.setattr(
        adapter._time,  # noqa: SLF001
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    code = adapter.logs(follow=True, tail=10)

    out = capsys.readouterr().out
    assert code == 130
    assert "No gateway log output available yet." in out


def test_start_terminates_spawned_child_when_state_write_fails(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)

    class _Process:
        pid = 9988

    def fake_popen(
        cmd: list[str],
        *,
        stdout,
        stderr,
        start_new_session: bool,
    ):
        return _Process()

    adapter = PosixDaemonAdapter(
        policy=_background_policy(),
        state_store=store,
        popen_factory=fake_popen,
    )
    monkeypatch.setattr(adapter, "_wait_for_stable_start", lambda _pid, timeout_s: True, raising=False)
    monkeypatch.setattr(store, "write_state", lambda _payload: (_ for _ in ()).throw(OSError("disk full")))

    kill_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.posix_daemon.os.kill",
        lambda pid, sig: kill_calls.append((pid, sig)),
    )
    monkeypatch.setattr(adapter, "_wait_for_exit", lambda _pid, _timeout_s: True)

    with pytest.raises(OSError, match="disk full"):
        adapter.start(GatewayStartOptions(port=19090))

    assert kill_calls[-1] == (9988, signal.SIGTERM)
    assert store.read_pid() is None


def test_start_fails_when_child_exits_during_startup_and_runs_cleanup(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)

    class _Process:
        pid = 7766

    def fake_popen(
        cmd: list[str],
        *,
        stdout,
        stderr,
        start_new_session: bool,
    ):
        return _Process()

    adapter = PosixDaemonAdapter(
        policy=_background_policy(),
        state_store=store,
        popen_factory=fake_popen,
    )
    cleanup_calls: list[int] = []
    monkeypatch.setattr(adapter, "_wait_for_stable_start", lambda _pid, timeout_s: False, raising=False)
    monkeypatch.setattr(adapter, "_cleanup_failed_start", lambda pid: cleanup_calls.append(pid))

    with pytest.raises(RuntimeError, match="background_process_exited_during_startup"):
        adapter.start(GatewayStartOptions(port=19090))

    assert cleanup_calls == [7766]
    assert store.read_pid() is None
    assert store.read_state() is None
