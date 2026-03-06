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
