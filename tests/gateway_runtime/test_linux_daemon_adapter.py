import signal
import subprocess

import pytest

from nanobot.gateway_runtime.models import GatewayStartOptions, RuntimeMode, RuntimePolicy
from nanobot.gateway_runtime.state_store import GatewayStateStore, build_gateway_instance_key


def _background_policy() -> RuntimePolicy:
    return RuntimePolicy(
        mode=RuntimeMode.BACKGROUND_MANAGED,
        reason="rollout_default_on",
        platform="Linux",
        rollout_stage="default_on",
    )


def test_start_spawns_linux_background_child_and_persists_runtime_files(
    tmp_path, monkeypatch
) -> None:
    from nanobot.gateway_runtime.adapters.linux_daemon import LinuxDaemonAdapter

    instance_key = build_gateway_instance_key(
        workspace="/tmp/work-a",
        config_path="/tmp/cfg-a.json",
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
        start_new_session: bool,
    ):
        captured["cmd"] = cmd
        captured["stderr"] = stderr
        captured["start_new_session"] = start_new_session
        captured["stdout_name"] = getattr(stdout, "name", "")
        return _Process()

    adapter = LinuxDaemonAdapter(
        policy=_background_policy(),
        state_store=store,
        python_executable="/mock/python",
        popen_factory=fake_popen,
    )
    monkeypatch.setattr(adapter, "_wait_for_stable_start", lambda _pid, timeout_s: True, raising=False)
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.linux_daemon.os.getpgid",
        lambda _pid: 9753,
    )

    result = adapter.start(
        GatewayStartOptions(
            port=19090,
            verbose=True,
            workspace="/tmp/work-a",
            config_path="/tmp/cfg-a.json",
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
        "/tmp/work-a",
        "--config",
        "/tmp/cfg-a.json",
    ]
    assert captured["stderr"] is subprocess.STDOUT
    assert captured["start_new_session"] is True

    state = store.read_state()
    assert state is not None
    assert state["mode"] == RuntimeMode.BACKGROUND_MANAGED.value
    assert state["platform"] == "Linux"
    assert state["pid"] == 2468
    assert state["pgid"] == 9753
    assert store.read_pid() == 2468
    assert store.resolve_log_path().exists()

    other_store = GatewayStateStore(
        data_dir=tmp_path,
        instance_key=build_gateway_instance_key(
            workspace="/tmp/work-b",
            config_path="/tmp/cfg-b.json",
        ),
    )
    assert other_store.read_pid() is None
    assert other_store.read_state() is None


def test_stop_prefers_process_group_and_escalates_to_sigkill_after_timeout(
    tmp_path, monkeypatch
) -> None:
    from nanobot.gateway_runtime.adapters.linux_daemon import LinuxDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(3579)
    store.write_state({"pid": 3579, "pgid": 4444, "mode": RuntimeMode.BACKGROUND_MANAGED.value})
    adapter = LinuxDaemonAdapter(policy=_background_policy(), state_store=store)

    group_kills: list[tuple[int, int]] = []
    pid_kills: list[tuple[int, int]] = []

    monkeypatch.setattr(adapter, "_wait_for_exit", lambda _pid, _timeout_s: False)
    monkeypatch.setattr(adapter, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.linux_daemon.os.killpg",
        lambda pgid, sig: group_kills.append((pgid, sig)),
    )
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.linux_daemon.os.kill",
        lambda pid, sig: pid_kills.append((pid, sig)),
    )
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.linux_daemon.os.getpgid",
        lambda pid: 4444,
    )

    result = adapter.stop(timeout_s=1)

    assert result.stopped is True
    assert result.mode is RuntimeMode.BACKGROUND_MANAGED
    assert group_kills[-2:] == [
        (4444, signal.SIGTERM),
        (4444, signal.SIGKILL),
    ]
    assert pid_kills == []
    assert store.read_pid() is None


def test_stop_falls_back_to_single_pid_signal_when_group_signal_fails(
    tmp_path, monkeypatch
) -> None:
    from nanobot.gateway_runtime.adapters.linux_daemon import LinuxDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(9911)
    store.write_state({"pid": 9911, "pgid": 5511, "mode": RuntimeMode.BACKGROUND_MANAGED.value})
    adapter = LinuxDaemonAdapter(policy=_background_policy(), state_store=store)

    group_kills: list[tuple[int, int]] = []
    pid_kills: list[tuple[int, int]] = []

    monkeypatch.setattr(adapter, "_wait_for_exit", lambda _pid, _timeout_s: True)
    monkeypatch.setattr(adapter, "_is_pid_running", lambda _pid: True)

    def fake_killpg(pgid: int, sig: int) -> None:
        group_kills.append((pgid, sig))
        raise ProcessLookupError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.linux_daemon.os.killpg",
        fake_killpg,
    )
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.linux_daemon.os.kill",
        lambda pid, sig: pid_kills.append((pid, sig)),
    )
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.linux_daemon.os.getpgid",
        lambda pid: 5511,
    )

    result = adapter.stop(timeout_s=1)

    assert result.stopped is True
    assert group_kills == [(5511, signal.SIGTERM)]
    assert pid_kills == [(9911, signal.SIGTERM)]
    assert store.read_pid() is None


def test_status_marks_stale_pid_with_explainable_reason(tmp_path, monkeypatch) -> None:
    from nanobot.gateway_runtime.adapters.linux_daemon import LinuxDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(2468)
    store.write_state(
        {
            "mode": RuntimeMode.BACKGROUND_MANAGED.value,
            "reason": "rollout_default_on",
            "platform": "Linux",
            "rollout_stage": "default_on",
            "pid": 2468,
            "pgid": 8642,
            "started_at": "t1",
        }
    )

    adapter = LinuxDaemonAdapter(policy=_background_policy(), state_store=store)
    monkeypatch.setattr(adapter, "_is_pid_running", lambda _pid: False)

    status = adapter.status()

    assert status.running is False
    assert status.pid is None
    assert status.pgid is None
    assert status.reason == "stale_pid_not_running"
    assert store.read_pid() is None


def test_logs_reads_gateway_log_file(tmp_path, capsys) -> None:
    from nanobot.gateway_runtime.adapters.linux_daemon import LinuxDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    log_path = store.resolve_log_path()
    log_path.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
    adapter = LinuxDaemonAdapter(policy=_background_policy(), state_store=store)

    code = adapter.logs(follow=False, tail=2)

    out = capsys.readouterr().out
    assert code == 0
    assert "line4" in out
    assert "line3" in out
    assert "line2" not in out


def test_logs_follow_keeps_waiting_when_file_is_initially_empty(tmp_path, monkeypatch, capsys) -> None:
    from nanobot.gateway_runtime.adapters.linux_daemon import LinuxDaemonAdapter

    store = GatewayStateStore(data_dir=tmp_path)
    store.resolve_log_path().write_text("", encoding="utf-8")
    adapter = LinuxDaemonAdapter(policy=_background_policy(), state_store=store)

    monkeypatch.setattr(
        adapter._time,  # noqa: SLF001
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    code = adapter.logs(follow=True, tail=10)

    out = capsys.readouterr().out
    assert code == 130
    assert "No gateway log output available yet." in out
