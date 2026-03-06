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


def test_facade_auto_mode_falls_back_to_legacy_on_daemon_start_failure(tmp_path, monkeypatch) -> None:
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
        "nanobot.gateway_runtime.facade.PosixDaemonAdapter",
        FailingDaemonAdapter,
        raising=False,
    )
    monkeypatch.setattr("nanobot.gateway_runtime.facade.ForegroundLegacyAdapter", LegacyAdapter)

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="rollout_default_on",
            platform="Darwin",
            rollout_stage="default_on",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    result = facade.start(GatewayStartOptions(cli_mode=None))

    assert result.mode is RuntimeMode.FOREGROUND_LEGACY
    assert calls["legacy_start"] == 1


def test_facade_explicit_background_does_not_silently_fallback(tmp_path, monkeypatch) -> None:
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
        "nanobot.gateway_runtime.facade.PosixDaemonAdapter",
        FailingDaemonAdapter,
        raising=False,
    )

    facade = GatewayRuntimeFacade(
        policy=RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="cli_override_background",
            platform="Darwin",
            rollout_stage="default_on",
        ),
        state_store=GatewayStateStore(data_dir=tmp_path),
    )

    with pytest.raises(RuntimeError, match="daemon start failed"):
        facade.start(GatewayStartOptions(cli_mode="background"))
