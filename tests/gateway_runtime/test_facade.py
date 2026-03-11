import pytest

from nanobot.gateway_runtime.facade import GatewayRuntimeFacade
from nanobot.gateway_runtime.models import (
    GatewayStartOptions,
    GatewayStatus,
    RestartResult,
    RuntimeMode,
    RuntimePolicy,
    StartResult,
)
from nanobot.gateway_runtime.state_store import GatewayStateStore


class StubAdapter:
    def __init__(self) -> None:
        self.started_with = None
        self.restarted_with = None
        self.logs_called_with = None

    def start(self, options: GatewayStartOptions) -> StartResult:
        self.started_with = options
        return StartResult(started=True, message="started", mode=RuntimeMode.FOREGROUND_LEGACY)

    def stop(self, timeout_s: int = 20):
        raise NotImplementedError

    def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
        self.restarted_with = (options, timeout_s)
        return RestartResult(restarted=False, message="legacy", mode=RuntimeMode.FOREGROUND_LEGACY)

    def status(self) -> GatewayStatus:
        return GatewayStatus(
            running=False,
            mode=RuntimeMode.FOREGROUND_LEGACY,
            reason="rollout_off",
            platform="Linux",
            rollout_stage="off",
        )

    def logs(self, follow: bool = True, tail: int = 200) -> int:
        self.logs_called_with = (follow, tail)
        return 0


def test_facade_delegates_calls_to_adapter() -> None:
    adapter = StubAdapter()
    facade = GatewayRuntimeFacade(adapter=adapter)

    start_result = facade.start(GatewayStartOptions(port=19999, verbose=True))
    restart_result = facade.restart(GatewayStartOptions(port=18888), timeout_s=12)
    status = facade.status()
    logs_code = facade.logs(follow=False, tail=20)

    assert start_result.started is True
    assert adapter.started_with is not None
    assert adapter.started_with.port == 19999

    assert restart_result.restarted is False
    assert adapter.restarted_with is not None
    _, timeout_s = adapter.restarted_with
    assert timeout_s == 12

    assert status.mode is RuntimeMode.FOREGROUND_LEGACY
    assert logs_code == 0
    assert adapter.logs_called_with == (False, 20)


def test_facade_builds_legacy_adapter_from_policy(tmp_path) -> None:
    called = {"count": 0}

    def run_foreground_loop(
        _port: int,
        _verbose: bool,
        _workspace: str | None,
        _config_path: str | None,
    ) -> None:
        called["count"] += 1

    facade = GatewayRuntimeFacade(
        run_foreground_loop=run_foreground_loop,
        policy=RuntimePolicy(
            mode=RuntimeMode.FOREGROUND_LEGACY,
            reason="rollout_off",
            platform="Darwin",
            rollout_stage="off",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    result = facade.start(GatewayStartOptions())

    assert result.mode is RuntimeMode.FOREGROUND_LEGACY
    assert called["count"] == 1


def test_facade_uses_daemon_adapter_for_darwin_background_policy(tmp_path, monkeypatch) -> None:
    daemon_called = {"count": 0}

    class StubDaemonAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            daemon_called["count"] += 1
            return StartResult(
                started=True,
                message="gateway_started_background_managed",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.PosixDaemonAdapter",
        StubDaemonAdapter,
        raising=False,
    )
    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="rollout_default_on",
            platform="Darwin",
            rollout_stage="default_on",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    result = facade.start(GatewayStartOptions())

    assert result.mode is RuntimeMode.BACKGROUND_MANAGED
    assert daemon_called["count"] == 1


def test_facade_uses_linux_daemon_adapter_for_linux_background_policy(tmp_path, monkeypatch) -> None:
    daemon_called = {"count": 0}

    class StubLinuxDaemonAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            daemon_called["count"] += 1
            return StartResult(
                started=True,
                message="gateway_started_background_managed",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.LinuxDaemonAdapter",
        StubLinuxDaemonAdapter,
        raising=False,
    )
    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="rollout_default_on",
            platform="Linux",
            rollout_stage="default_on",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    result = facade.start(GatewayStartOptions())

    assert result.mode is RuntimeMode.BACKGROUND_MANAGED
    assert daemon_called["count"] == 1


def test_facade_auto_mode_falls_back_to_legacy_on_linux_daemon_start_failure(tmp_path, monkeypatch) -> None:
    calls = {"legacy_start": 0}

    class FailingDaemonAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise RuntimeError("daemon start failed")

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    class LegacyAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            calls["legacy_start"] += 1
            return StartResult(
                started=True,
                message="gateway_started_foreground_legacy",
                mode=RuntimeMode.FOREGROUND_LEGACY,
            )

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.LinuxDaemonAdapter",
        FailingDaemonAdapter,
        raising=False,
    )
    monkeypatch.setattr("nanobot.gateway_runtime.facade.ForegroundLegacyAdapter", LegacyAdapter)

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="rollout_default_on",
            platform="Linux",
            rollout_stage="default_on",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    result = facade.start(GatewayStartOptions(cli_mode=None))

    assert result.mode is RuntimeMode.FOREGROUND_LEGACY
    assert calls["legacy_start"] == 1


def test_facade_explicit_background_does_not_silently_fallback_on_linux(tmp_path, monkeypatch) -> None:
    class FailingDaemonAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise RuntimeError("daemon start failed")

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.LinuxDaemonAdapter",
        FailingDaemonAdapter,
        raising=False,
    )

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="cli_override_background",
            platform="Linux",
            rollout_stage="default_on",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    with pytest.raises(RuntimeError, match="daemon start failed"):
        facade.start(GatewayStartOptions(cli_mode="background"))


def test_facade_uses_recorded_foreground_state_for_linux_follow_up_commands(tmp_path, monkeypatch) -> None:
    calls = {"legacy_status": 0, "linux_status": 0}
    store = GatewayStateStore(data_dir=tmp_path)
    store.write_state(
        {
            "mode": RuntimeMode.FOREGROUND_LEGACY.value,
            "reason": "cli_override_foreground",
            "platform": "Linux",
            "rollout_stage": "default_on",
        }
    )

    class LegacyAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise NotImplementedError

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            calls["legacy_status"] += 1
            return GatewayStatus(
                running=False,
                mode=RuntimeMode.FOREGROUND_LEGACY,
                reason="cli_override_foreground",
                platform="Linux",
                rollout_stage="default_on",
            )

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    class LinuxAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise NotImplementedError

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            calls["linux_status"] += 1
            return GatewayStatus(
                running=True,
                mode=RuntimeMode.BACKGROUND_MANAGED,
                reason="rollout_default_on",
                platform="Linux",
                rollout_stage="default_on",
            )

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr("nanobot.gateway_runtime.facade.ForegroundLegacyAdapter", LegacyAdapter)
    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.LinuxDaemonAdapter",
        LinuxAdapter,
        raising=False,
    )

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="rollout_default_on",
            platform="Linux",
            rollout_stage="default_on",
        ),
        state_store=store,
        prefer_recorded_mode=True,
    )

    status = facade.status()

    assert status.mode is RuntimeMode.FOREGROUND_LEGACY
    assert calls["legacy_status"] == 1
    assert calls["linux_status"] == 0


def test_facade_explicit_background_overrides_recorded_legacy_state(tmp_path, monkeypatch) -> None:
    calls = {"legacy_start": 0, "linux_start": 0}
    store = GatewayStateStore(data_dir=tmp_path)
    store.write_state(
        {
            "mode": RuntimeMode.FOREGROUND_LEGACY.value,
            "reason": "cli_override_foreground",
            "platform": "Linux",
            "rollout_stage": "default_on",
        }
    )

    class LegacyAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            calls["legacy_start"] += 1
            return StartResult(
                started=True,
                message="gateway_started_foreground_legacy",
                mode=RuntimeMode.FOREGROUND_LEGACY,
            )

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    class LinuxAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            calls["linux_start"] += 1
            return StartResult(
                started=True,
                message="gateway_started_background_managed",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr("nanobot.gateway_runtime.facade.ForegroundLegacyAdapter", LegacyAdapter)
    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.LinuxDaemonAdapter",
        LinuxAdapter,
        raising=False,
    )

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="cli_override_background",
            platform="Linux",
            rollout_stage="default_on",
        ),
        state_store=store,
        prefer_recorded_mode=True,
    )

    result = facade.start(GatewayStartOptions(cli_mode="background"))

    assert result.mode is RuntimeMode.BACKGROUND_MANAGED
    assert calls["linux_start"] == 1
    assert calls["legacy_start"] == 0


def test_facade_restart_preserves_live_linux_legacy_guard_even_with_background_override(
    tmp_path, monkeypatch
) -> None:
    calls = {"legacy_restart": 0, "linux_restart": 0}
    store = GatewayStateStore(data_dir=tmp_path)
    store.write_state(
        {
            "mode": RuntimeMode.FOREGROUND_LEGACY.value,
            "reason": "cli_override_foreground",
            "platform": "Linux",
            "rollout_stage": "default_on",
        }
    )
    store.write_pid(4321)

    class LegacyAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise NotImplementedError

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            calls["legacy_restart"] += 1
            return RestartResult(
                restarted=False,
                message="legacy_foreground_requires_manual_restart",
                mode=RuntimeMode.FOREGROUND_LEGACY,
            )

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    class LinuxAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise NotImplementedError

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            calls["linux_restart"] += 1
            return RestartResult(
                restarted=True,
                message="gateway_restarted_background_managed",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr("nanobot.gateway_runtime.facade.ForegroundLegacyAdapter", LegacyAdapter)
    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.LinuxDaemonAdapter",
        LinuxAdapter,
        raising=False,
    )
    monkeypatch.setattr(
        GatewayRuntimeFacade,
        "_is_pid_running",
        lambda self, pid: pid == 4321,
    )

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="cli_override_background",
            platform="Linux",
            rollout_stage="default_on",
        ),
        state_store=store,
        prefer_recorded_mode=True,
        preserve_live_legacy_restart_guard=True,
    )

    result = facade.restart(GatewayStartOptions(cli_mode="background"))

    assert result.mode is RuntimeMode.FOREGROUND_LEGACY
    assert calls["legacy_restart"] == 1
    assert calls["linux_restart"] == 0


def test_facade_selects_windows_daemon_adapter_for_background_mode(tmp_path, monkeypatch) -> None:
    calls = {"windows_status": 0}
    store = GatewayStateStore(data_dir=tmp_path)
    captured: dict[str, object] = {}

    class WindowsAdapter:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise NotImplementedError

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            calls["windows_status"] += 1
            return GatewayStatus(
                running=True,
                mode=RuntimeMode.BACKGROUND_MANAGED,
                reason="rollout_default_on",
                platform="Windows",
                rollout_stage="default_on",
            )

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.WindowsDaemonAdapter",
        WindowsAdapter,
        raising=False,
    )

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="rollout_default_on",
            platform="Windows",
            rollout_stage="default_on",
        ),
        state_store=store,
    )

    status = facade.status()

    assert status.mode is RuntimeMode.BACKGROUND_MANAGED
    assert calls["windows_status"] == 1
    assert captured["state_store"] is store



def test_facade_auto_mode_falls_back_to_legacy_on_windows_daemon_start_failure(tmp_path, monkeypatch) -> None:
    calls = {"legacy_start": 0, "windows_start": 0}

    class FailingWindowsAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            calls["windows_start"] += 1
            raise RuntimeError("daemon start failed")

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    class LegacyAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            calls["legacy_start"] += 1
            return StartResult(
                started=True,
                message="gateway_started_foreground_legacy",
                mode=RuntimeMode.FOREGROUND_LEGACY,
            )

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.WindowsDaemonAdapter",
        FailingWindowsAdapter,
        raising=False,
    )
    monkeypatch.setattr("nanobot.gateway_runtime.facade.ForegroundLegacyAdapter", LegacyAdapter)

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="rollout_default_on",
            platform="Windows",
            rollout_stage="default_on",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    result = facade.start(GatewayStartOptions(cli_mode=None))

    assert result.mode is RuntimeMode.FOREGROUND_LEGACY
    assert calls == {"legacy_start": 1, "windows_start": 1}



def test_facade_explicit_background_does_not_silently_fallback_on_windows(tmp_path, monkeypatch) -> None:
    class FailingWindowsAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise RuntimeError("daemon start failed")

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.WindowsDaemonAdapter",
        FailingWindowsAdapter,
        raising=False,
    )

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="cli_override_background",
            platform="Windows",
            rollout_stage="default_on",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    with pytest.raises(RuntimeError, match="daemon start failed"):
        facade.start(GatewayStartOptions(cli_mode="background"))



def test_facade_kill_switch_policy_stays_on_legacy_and_does_not_enter_windows_adapter(
    tmp_path, monkeypatch
) -> None:
    calls = {"legacy_status": 0, "windows_init": 0}

    class LegacyAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise NotImplementedError

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            calls["legacy_status"] += 1
            return GatewayStatus(
                running=False,
                mode=RuntimeMode.FOREGROUND_LEGACY,
                reason="kill_switch_enabled",
                platform="Windows",
                rollout_stage="default_on",
            )

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    class WindowsAdapter:
        def __init__(self, **_kwargs) -> None:
            calls["windows_init"] += 1

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise NotImplementedError

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr("nanobot.gateway_runtime.facade.ForegroundLegacyAdapter", LegacyAdapter)
    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.WindowsDaemonAdapter",
        WindowsAdapter,
        raising=False,
    )

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.FOREGROUND_LEGACY,
            reason="kill_switch_enabled",
            platform="Windows",
            rollout_stage="default_on",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    status = facade.status()

    assert status.mode is RuntimeMode.FOREGROUND_LEGACY
    assert calls == {"legacy_status": 1, "windows_init": 0}


def test_facade_restart_background_preserves_live_windows_legacy_guard_without_posix_kill(
    tmp_path, monkeypatch
) -> None:
    calls = {"legacy_restart": 0, "windows_restart": 0, "windows_probe": 0}
    store = GatewayStateStore(data_dir=tmp_path)
    store.write_state(
        {
            "mode": RuntimeMode.FOREGROUND_LEGACY.value,
            "reason": "cli_override_foreground",
            "platform": "Windows",
            "rollout_stage": "default_on",
        }
    )
    store.write_pid(4321)

    class LegacyAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise NotImplementedError

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            calls["legacy_restart"] += 1
            return RestartResult(
                restarted=False,
                message="legacy_foreground_requires_manual_restart",
                mode=RuntimeMode.FOREGROUND_LEGACY,
            )

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    class WindowsAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options: GatewayStartOptions) -> StartResult:
            raise NotImplementedError

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
            calls["windows_restart"] += 1
            return RestartResult(
                restarted=True,
                message="gateway_restarted_background_managed",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr("nanobot.gateway_runtime.facade.ForegroundLegacyAdapter", LegacyAdapter)
    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.WindowsDaemonAdapter",
        WindowsAdapter,
        raising=False,
    )
    monkeypatch.setattr(
        GatewayRuntimeFacade,
        "_is_pid_running_windows",
        lambda self, pid: calls.__setitem__("windows_probe", calls["windows_probe"] + 1) or pid == 4321,
        raising=False,
    )
    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.os.kill",
        lambda pid, sig: (_ for _ in ()).throw(AssertionError("posix kill probe should not be used on Windows")),
    )

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="cli_override_background",
            platform="Windows",
            rollout_stage="default_on",
        ),
        state_store=store,
        prefer_recorded_mode=True,
        preserve_live_legacy_restart_guard=True,
    )

    result = facade.restart(GatewayStartOptions(cli_mode="background"))

    assert result.mode is RuntimeMode.FOREGROUND_LEGACY
    assert calls == {"legacy_restart": 1, "windows_restart": 0, "windows_probe": 1}
