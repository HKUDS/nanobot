import subprocess

from nanobot.gateway_runtime.models import (
    GatewayStartOptions,
    GatewayStatus,
    RestartResult,
    RuntimeMode,
    RuntimePolicy,
    StartResult,
    StopResult,
)
from nanobot.gateway_runtime.state_store import GatewayStateStore, build_gateway_instance_key


CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CTRL_BREAK_EVENT = 1


def _background_policy() -> RuntimePolicy:
    return RuntimePolicy(
        mode=RuntimeMode.BACKGROUND_MANAGED,
        reason="rollout_default_on",
        platform="Windows",
        rollout_stage="default_on",
    )


def test_get_process_identity_configures_win32_signatures_before_open_process(tmp_path) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    class _Fn:
        def __init__(self, ret=None):
            self.restype = None
            self.argtypes = None
            self._ret = ret

        def __call__(self, *args):
            assert self.restype is not None
            assert self.argtypes is not None
            return self._ret

    class _Kernel32:
        def __init__(self):
            self.OpenProcess = _Fn(ret=1234)
            self.GetProcessTimes = _Fn(ret=1)
            self.GetExitCodeProcess = _Fn(ret=1)
            self.CloseHandle = _Fn(ret=1)
            self.GetLastError = _Fn(ret=0)

    adapter = WindowsDaemonAdapter(
        policy=_background_policy(),
        state_store=GatewayStateStore(data_dir=tmp_path),
        kernel32=_Kernel32(),
    )

    identity = adapter._get_process_identity(4321)

    assert identity is not None


def test_start_spawns_windows_background_child_and_persists_runtime_files(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    instance_key = build_gateway_instance_key(
        workspace=r"C:\\tmp\\work-a",
        config_path=r"C:\\tmp\\cfg-a.json",
    )
    assert instance_key is not None
    store = GatewayStateStore(data_dir=tmp_path, instance_key=instance_key)
    captured: dict[str, object] = {}

    class _Process:
        pid = 2468

    def fake_popen(
        cmd: list[str],
        *,
        stdout,
        stderr,
        creationflags: int,
    ):
        captured["cmd"] = cmd
        captured["stderr"] = stderr
        captured["creationflags"] = creationflags
        captured["stdout_name"] = getattr(stdout, "name", "")
        return _Process()

    adapter = WindowsDaemonAdapter(
        policy=_background_policy(),
        state_store=store,
        python_executable="/mock/python",
        popen_factory=fake_popen,
        create_new_process_group=CREATE_NEW_PROCESS_GROUP,
        create_no_window=CREATE_NO_WINDOW,
        ctrl_break_event=CTRL_BREAK_EVENT,
    )
    monkeypatch.setattr(adapter, "_wait_for_stable_start", lambda _pid, timeout_s: True, raising=False)
    monkeypatch.setattr(adapter, "_get_process_identity", lambda _pid: "created:2468", raising=False)

    result = adapter.start(
        GatewayStartOptions(
            port=19090,
            verbose=True,
            workspace=r"C:\\tmp\\work-a",
            config_path=r"C:\\tmp\\cfg-a.json",
        )
    )

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
        "--workspace",
        r"C:\\tmp\\work-a",
        "--config",
        r"C:\\tmp\\cfg-a.json",
    ]
    assert captured["stderr"] is subprocess.STDOUT
    assert captured["creationflags"] == CREATE_NEW_PROCESS_GROUP

    state = store.read_state()
    assert state is not None
    assert state["mode"] == RuntimeMode.BACKGROUND_MANAGED.value
    assert state["platform"] == "Windows"
    assert state["pid"] == 2468
    assert state["process_identity"] == "created:2468"
    assert store.read_pid() == 2468
    assert store.resolve_log_path().exists()

    other_store = GatewayStateStore(
        data_dir=tmp_path,
        instance_key=build_gateway_instance_key(
            workspace=r"C:\\tmp\\work-b",
            config_path=r"C:\\tmp\\cfg-b.json",
        ),
    )
    assert other_store.read_pid() is None
    assert other_store.read_state() is None


def test_status_marks_pid_reuse_as_identity_mismatch(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(3579)
    store.write_state(
        {
            "mode": RuntimeMode.BACKGROUND_MANAGED.value,
            "reason": "rollout_default_on",
            "platform": "Windows",
            "rollout_stage": "default_on",
            "pid": 3579,
            "process_identity": "created:old",
        }
    )
    adapter = WindowsDaemonAdapter(policy=_background_policy(), state_store=store)
    monkeypatch.setattr(adapter, "_probe_pid_running", lambda _pid: True, raising=False)
    monkeypatch.setattr(adapter, "_validate_process_identity", lambda _state, _pid: False, raising=False)

    status = adapter.status()

    assert status == GatewayStatus(
        running=False,
        mode=RuntimeMode.BACKGROUND_MANAGED,
        reason="stale_pid_identity_mismatch",
        platform="Windows",
        rollout_stage="default_on",
        pid=None,
        log_path=store.resolve_log_path(),
        started_at=None,
    )
    assert store.read_pid() is None


def test_status_keeps_pid_when_windows_probe_is_access_denied(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(3579)
    store.write_state(
        {
            "mode": RuntimeMode.BACKGROUND_MANAGED.value,
            "reason": "rollout_default_on",
            "platform": "Windows",
            "rollout_stage": "default_on",
            "pid": 3579,
            "process_identity": "created:3579",
            "started_at": "2026-03-03T00:00:00Z",
        }
    )
    adapter = WindowsDaemonAdapter(policy=_background_policy(), state_store=store)
    monkeypatch.setattr(adapter, "_probe_pid_running", lambda _pid: None, raising=False)

    status = adapter.status()

    assert status == GatewayStatus(
        running=False,
        mode=RuntimeMode.BACKGROUND_MANAGED,
        reason="process_status_unknown_access_denied",
        platform="Windows",
        rollout_stage="default_on",
        pid=3579,
        log_path=store.resolve_log_path(),
        started_at="2026-03-03T00:00:00Z",
    )
    assert store.read_pid() == 3579


def test_status_repairs_stale_windows_pid(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(3579)
    store.write_state(
        {
            "mode": RuntimeMode.BACKGROUND_MANAGED.value,
            "reason": "rollout_default_on",
            "platform": "Windows",
            "rollout_stage": "default_on",
            "pid": 3579,
        }
    )
    adapter = WindowsDaemonAdapter(policy=_background_policy(), state_store=store)
    monkeypatch.setattr(adapter, "_probe_pid_running", lambda _pid: False, raising=False)

    status = adapter.status()

    assert status == GatewayStatus(
        running=False,
        mode=RuntimeMode.BACKGROUND_MANAGED,
        reason="stale_pid_not_running",
        platform="Windows",
        rollout_stage="default_on",
        pid=None,
        log_path=store.resolve_log_path(),
        started_at=None,
    )
    assert store.read_pid() is None


def test_stop_refuses_to_signal_when_windows_process_identity_mismatches(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(4567)
    store.write_state(
        {
            "mode": RuntimeMode.BACKGROUND_MANAGED.value,
            "reason": "rollout_default_on",
            "platform": "Windows",
            "rollout_stage": "default_on",
            "pid": 4567,
            "process_identity": "created:old",
        }
    )
    adapter = WindowsDaemonAdapter(
        policy=_background_policy(),
        state_store=store,
        ctrl_break_event=CTRL_BREAK_EVENT,
    )

    kill_calls: list[tuple[int, int]] = []
    taskkill_calls: list[list[str]] = []

    monkeypatch.setattr(adapter, "_probe_pid_running", lambda _pid: True, raising=False)
    monkeypatch.setattr(adapter, "_validate_process_identity", lambda _state, _pid: False, raising=False)
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.windows_daemon.os.kill",
        lambda pid, sig: kill_calls.append((pid, sig)),
    )
    monkeypatch.setattr(adapter, "_run_subprocess", lambda cmd: taskkill_calls.append(cmd))

    result = adapter.stop(timeout_s=1)

    assert result == StopResult(
        stopped=False,
        message="background_process_identity_mismatch",
        mode=RuntimeMode.BACKGROUND_MANAGED,
    )
    assert kill_calls == []
    assert taskkill_calls == []
    assert store.read_pid() is None


def test_stop_uses_layered_windows_termination_strategy(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(4567)
    store.write_state(
        {
            "mode": RuntimeMode.BACKGROUND_MANAGED.value,
            "reason": "rollout_default_on",
            "platform": "Windows",
            "rollout_stage": "default_on",
            "pid": 4567,
            "process_identity": "created:4567",
        }
    )
    adapter = WindowsDaemonAdapter(
        policy=_background_policy(),
        state_store=store,
        ctrl_break_event=CTRL_BREAK_EVENT,
    )

    kill_calls: list[tuple[int, int]] = []
    taskkill_calls: list[list[str]] = []
    wait_results = iter([False, False, False])

    monkeypatch.setattr(adapter, "_probe_pid_running", lambda _pid: True, raising=False)
    monkeypatch.setattr(adapter, "_validate_process_identity", lambda _state, _pid: True, raising=False)
    monkeypatch.setattr(adapter, "_wait_for_exit", lambda _pid, _timeout_s: next(wait_results))
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.windows_daemon.os.kill",
        lambda pid, sig: kill_calls.append((pid, sig)),
    )
    monkeypatch.setattr(
        adapter,
        "_run_subprocess",
        lambda cmd: taskkill_calls.append(cmd),
    )

    result = adapter.stop(timeout_s=1)

    assert result == StopResult(
        stopped=True,
        message="gateway_stopped_background_managed",
        mode=RuntimeMode.BACKGROUND_MANAGED,
    )
    assert kill_calls == [(4567, CTRL_BREAK_EVENT)]
    assert taskkill_calls == [
        ["taskkill", "/PID", "4567", "/T"],
        ["taskkill", "/PID", "4567", "/T", "/F"],
    ]
    assert store.read_pid() is None


def test_restart_does_not_start_when_windows_stop_cannot_determine_process_state(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    adapter = WindowsDaemonAdapter(
        policy=_background_policy(),
        state_store=GatewayStateStore(data_dir=tmp_path),
        ctrl_break_event=CTRL_BREAK_EVENT,
    )
    calls: list[str] = []

    def fake_stop(timeout_s: int = 20) -> StopResult:
        calls.append(f"stop:{timeout_s}")
        return StopResult(
            stopped=False,
            message="background_process_status_unknown",
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

    assert result == RestartResult(
        restarted=False,
        message="background_process_status_unknown",
        mode=RuntimeMode.BACKGROUND_MANAGED,
    )
    assert calls == ["stop:9"]


def test_restart_performs_stop_then_start(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    adapter = WindowsDaemonAdapter(
        policy=_background_policy(),
        state_store=GatewayStateStore(data_dir=tmp_path),
        ctrl_break_event=CTRL_BREAK_EVENT,
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

    assert result == RestartResult(
        restarted=True,
        message="gateway_restarted_background_managed",
        mode=RuntimeMode.BACKGROUND_MANAGED,
    )
    assert calls == ["stop:9", "start"]


def test_logs_reads_instance_specific_gateway_log_file(tmp_path, capsys) -> None:
    from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter

    instance_key = build_gateway_instance_key(
        workspace=r"C:\\tmp\\work-a",
        config_path=r"C:\\tmp\\cfg-a.json",
    )
    assert instance_key is not None
    store = GatewayStateStore(data_dir=tmp_path, instance_key=instance_key)
    log_path = store.resolve_log_path()
    log_path.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
    adapter = WindowsDaemonAdapter(
        policy=_background_policy(),
        state_store=store,
        ctrl_break_event=CTRL_BREAK_EVENT,
    )

    code = adapter.logs(follow=False, tail=2)

    out = capsys.readouterr().out
    assert code == 0
    assert "line4" in out
    assert "line3" in out
    assert "line2" not in out
