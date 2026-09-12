"""External monitor recovery decisions and crash-safe bounded restart attempts."""

from unittest.mock import Mock

import pytest

from nanobot.operations import supervisor
from nanobot.operations.state import read_state, write_state
from nanobot.operations.supervisor import ServiceState, decide


def decision(*, pid=7, active=True, healthy=True, heartbeat=None, now=2000, started=1000):
    return decide(
        ServiceState(active, pid, started), healthy=healthy,
        heartbeat=heartbeat if heartbeat is not None else {"pid": pid, "monotonic_at": now - 30},
        recovery_enabled=True, interval_seconds=600, now_monotonic=now,
    )


def test_fresh_live_gateway_and_goal_watchdog_are_left_running():
    assert decision().action == "healthy"
    assert decision(now=1050, healthy=False).reason == "gateway_starting"


def test_gateway_hang_or_stopped_service_requests_restart():
    assert decision(healthy=False).reason == "gateway_unresponsive"
    assert decision(active=False, pid=0).reason == "gateway_stopped"


@pytest.mark.parametrize("heartbeat", [
    {}, {"pid": 8, "monotonic_at": 1980}, {"pid": 7, "monotonic_at": 900},
    {"pid": 7, "monotonic_at": 3000}, {"pid": 7, "monotonic_at": float("nan")},
])
def test_previous_process_or_invalid_heartbeat_cannot_claim_liveness(heartbeat):
    assert decision(heartbeat=heartbeat).reason == "goal_watchdog_unresponsive"


def test_heartbeat_expiry_even_when_gateway_http_still_works():
    assert decision(now=4000, heartbeat={"pid": 7, "monotonic_at": 2000}).action == "restart"


def test_restart_attempt_is_durable_before_systemd_action_and_bounded(tmp_path, monkeypatch):
    state_path = tmp_path / "supervisor.json"
    monkeypatch.setattr(supervisor, "service_state", lambda _: ServiceState(False, 0, 0))
    calls = []

    def restart(argv, **kwargs):
        attempts = read_state(state_path)["restart_attempts"]
        assert len(attempts) == len(calls) + 1
        calls.append(argv)

    monkeypatch.setattr(supervisor.subprocess, "run", restart)
    arguments = dict(unit="nanobot.service", state_path=state_path,
                     heartbeat_path=tmp_path / "heartbeat.json", port=18790,
                     recovery_enabled=True, interval_seconds=600)
    for _ in range(3):
        assert supervisor.check(**arguments)["action"] == "restart"
    assert supervisor.check(**arguments)["action"] == "held"
    assert len(calls) == 3
    assert all(argv == ["systemctl", "restart", "--no-block", "nanobot.service"] for argv in calls)


def test_transient_health_failure_is_rechecked_without_restarting(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "service_state", lambda _: ServiceState(True, 7, 1))
    probe = Mock(side_effect=[False, True])
    monkeypatch.setattr(supervisor, "health_probe", probe)
    result = supervisor.check(unit="nanobot.service", state_path=tmp_path / "supervisor.json",
                              heartbeat_path=tmp_path / "none", port=18790,
                              recovery_enabled=False, interval_seconds=600)
    assert result["action"] == "healthy" and probe.call_count == 2


def test_paused_monitor_does_not_touch_service_or_clear_restart_budget(tmp_path, monkeypatch):
    state_path = tmp_path / "supervisor.json"
    write_state(state_path, {"paused": True, "restart_attempts": [123]})
    inspect = Mock(side_effect=AssertionError("operator paused"))
    monkeypatch.setattr(supervisor, "service_state", inspect)
    assert supervisor.check(unit="nanobot.service", state_path=state_path,
                            heartbeat_path=tmp_path / "none", port=18790,
                            recovery_enabled=True, interval_seconds=600)["action"] == "paused"
    assert read_state(state_path)["restart_attempts"] == [123]
    inspect.assert_not_called()


def test_service_option_injection_rejected_before_running_systemctl(monkeypatch):
    run = Mock()
    monkeypatch.setattr(supervisor.subprocess, "run", run)
    with pytest.raises(ValueError):
        supervisor.service_state("--system.service")
    run.assert_not_called()
