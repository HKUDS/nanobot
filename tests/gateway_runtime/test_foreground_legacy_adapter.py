from nanobot.gateway_runtime.adapters.foreground_legacy import ForegroundLegacyAdapter
from nanobot.gateway_runtime.models import GatewayStartOptions, RuntimeMode, RuntimePolicy
from nanobot.gateway_runtime.state_store import GatewayStateStore


def _legacy_policy() -> RuntimePolicy:
    return RuntimePolicy(
        mode=RuntimeMode.FOREGROUND_LEGACY,
        reason="rollout_off",
        platform="Linux",
        rollout_stage="off",
    )


def _windows_legacy_policy() -> RuntimePolicy:
    return RuntimePolicy(
        mode=RuntimeMode.FOREGROUND_LEGACY,
        reason="rollout_off",
        platform="Windows",
        rollout_stage="off",
    )


def test_start_delegates_to_foreground_runner_and_writes_state(tmp_path) -> None:
    called: dict[str, tuple[int, bool]] = {}

    def run_foreground_loop(
        port: int,
        verbose: bool,
        workspace: str | None,
        config_path: str | None,
    ) -> None:
        called["args"] = (port, verbose)
        called["workspace"] = workspace
        called["config_path"] = config_path

    adapter = ForegroundLegacyAdapter(
        run_foreground_loop=run_foreground_loop,
        policy=_legacy_policy(),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    result = adapter.start(
        GatewayStartOptions(
            port=19001,
            verbose=True,
            workspace="/tmp/work-a",
            config_path="/tmp/cfg-a.json",
        )
    )

    assert called["args"] == (19001, True)
    assert called["workspace"] == "/tmp/work-a"
    assert called["config_path"] == "/tmp/cfg-a.json"
    assert result.started is True
    assert result.mode is RuntimeMode.FOREGROUND_LEGACY

    state = GatewayStateStore(data_dir=tmp_path).read_state()
    assert state is not None
    assert state["mode"] == RuntimeMode.FOREGROUND_LEGACY.value


def test_restart_returns_non_destructive_result_in_legacy_mode(tmp_path) -> None:
    adapter = ForegroundLegacyAdapter(
        run_foreground_loop=lambda _port, _verbose, _workspace, _config_path: None,
        policy=_legacy_policy(),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    result = adapter.restart(GatewayStartOptions())

    assert result.restarted is False
    assert "legacy" in result.message


def test_status_reports_current_policy_context(tmp_path) -> None:
    adapter = ForegroundLegacyAdapter(
        run_foreground_loop=lambda _port, _verbose, _workspace, _config_path: None,
        policy=_legacy_policy(),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    status = adapter.status()

    assert status.running is False
    assert status.mode is RuntimeMode.FOREGROUND_LEGACY
    assert status.platform == "Linux"
    assert status.reason == "rollout_off"


def test_logs_in_legacy_mode_prints_explanatory_hint(tmp_path, capsys) -> None:
    adapter = ForegroundLegacyAdapter(
        run_foreground_loop=lambda _port, _verbose, _workspace, _config_path: None,
        policy=_legacy_policy(),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    code = adapter.logs(follow=False, tail=10)

    captured = capsys.readouterr()
    assert code == 0
    assert "foreground mode" in captured.out.lower()


import os


def test_start_records_current_pid_while_foreground_loop_is_running_and_clears_after(tmp_path) -> None:
    store = GatewayStateStore(data_dir=tmp_path)
    observed: dict[str, int | None] = {"during": None}

    def run_foreground_loop(
        port: int,
        verbose: bool,
        workspace: str | None,
        config_path: str | None,
    ) -> None:
        observed["during"] = store.read_pid()

    adapter = ForegroundLegacyAdapter(
        run_foreground_loop=run_foreground_loop,
        policy=_legacy_policy(),
        state_store=store,
    )

    result = adapter.start(GatewayStartOptions())

    assert result.started is True
    assert observed["during"] == os.getpid()
    assert store.read_pid() is None



def test_status_clears_stale_pid_file_for_unclean_legacy_exit(tmp_path, monkeypatch) -> None:
    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(4242)
    adapter = ForegroundLegacyAdapter(
        run_foreground_loop=lambda _port, _verbose, _workspace, _config_path: None,
        policy=_legacy_policy(),
        state_store=store,
    )
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.foreground_legacy.os.kill",
        lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError),
    )

    status = adapter.status()

    assert status.running is False
    assert status.pid is None
    assert store.read_pid() is None



def test_status_uses_windows_safe_liveness_probe_without_os_kill(tmp_path, monkeypatch) -> None:
    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(4242)
    adapter = ForegroundLegacyAdapter(
        run_foreground_loop=lambda _port, _verbose, _workspace, _config_path: None,
        policy=_windows_legacy_policy(),
        state_store=store,
    )
    monkeypatch.setattr(
        adapter,
        "_is_pid_running_windows",
        lambda pid: pid == 4242,
        raising=False,
    )
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.foreground_legacy.os.kill",
        lambda pid, sig: (_ for _ in ()).throw(AssertionError("os.kill should not be used on Windows")),
    )

    status = adapter.status()

    assert status.running is True
    assert status.pid == 4242



def test_status_clears_stale_pid_file_on_windows_without_os_kill(tmp_path, monkeypatch) -> None:
    store = GatewayStateStore(data_dir=tmp_path)
    store.write_pid(4242)
    adapter = ForegroundLegacyAdapter(
        run_foreground_loop=lambda _port, _verbose, _workspace, _config_path: None,
        policy=_windows_legacy_policy(),
        state_store=store,
    )
    monkeypatch.setattr(
        adapter,
        "_is_pid_running_windows",
        lambda pid: False,
        raising=False,
    )
    monkeypatch.setattr(
        "nanobot.gateway_runtime.adapters.foreground_legacy.os.kill",
        lambda pid, sig: (_ for _ in ()).throw(AssertionError("os.kill should not be used on Windows")),
    )

    status = adapter.status()

    assert status.running is False
    assert status.pid is None
    assert store.read_pid() is None
