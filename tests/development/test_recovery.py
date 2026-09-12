from __future__ import annotations

from unittest.mock import Mock

import pytest
from filelock import FileLock

from nanobot.development import recovery
from nanobot.development.config import DevelopmentConfig
from nanobot.development.models import Requirement
from nanobot.development.service import DevelopmentService
from nanobot.operations.state import read_state


def setup(tmp_path):
    config = DevelopmentConfig(enable=True, repository=str(tmp_path), owner_session_key="telegram:owner",
                               worker_backend="systemd")
    config_path = tmp_path / "config.json"
    service = DevelopmentService(config, tmp_path / "workspace", config_path)
    service.store.initialize("Full project", [Requirement(id="feature", description="A verified change")])
    job = service.store.propose(title="Change", objective="Implement change", evidence=["Missing behavior"],
                                acceptance=["Working behavior"], requirement_ids=["feature"])
    service.store.set_paused(False)
    service.store.claim(job.id)
    return service, job, config_path


def test_interruption_preserves_phase_and_dispatches_with_durable_budget(tmp_path, monkeypatch):
    service, job, config_path = setup(tmp_path)
    service.store.update_job(job.id, lambda item: setattr(item, "stage", "checking"))
    calls = []

    def start(instance, job_id):
        record = read_state(instance.store.root / "recovery.json")
        assert len(record["attempts"]) == len(calls) + 1
        assert instance.store.read().jobs[0].checkpoint_stage == "checking"
        calls.append(job_id)
        return "Started"

    monkeypatch.setattr(DevelopmentService, "start", start)
    for _ in range(3):
        record = recovery.recover(service.config, tmp_path / "workspace", config_path)
        assert record.action == "resume"
    assert recovery.recover(service.config, tmp_path / "workspace", config_path).reason == "resume_budget_exhausted"
    assert calls == [job.id] * 3


def test_live_worker_and_owner_pause_are_not_overridden(tmp_path, monkeypatch):
    service, _, config_path = setup(tmp_path)
    start = Mock()
    monkeypatch.setattr(DevelopmentService, "start", start)
    with FileLock(str(service.store.root / "worker.lock")):
        assert recovery.recover(service.config, tmp_path / "workspace", config_path).action == "idle"
    service.store.set_paused(True)
    assert recovery.recover(service.config, tmp_path / "workspace", config_path).action == "paused"
    start.assert_not_called()


def test_budget_hold_waits_until_next_utc_day(tmp_path, monkeypatch):
    service, job, config_path = setup(tmp_path)

    def held(item):
        item.stage, item.checkpoint_stage, item.hold_kind = "held", "building", "budget"

    service.store.update_job(job.id, held)
    start = Mock()
    monkeypatch.setattr(DevelopmentService, "start", start)
    now = service.store.read().jobs[0].updated_at
    assert recovery.recover(service.config, tmp_path / "workspace", config_path).reason == "daily_budget_waiting_for_reset"
    start.assert_not_called()
    monkeypatch.setattr(recovery.time, "time", lambda: now + 86400)
    assert recovery.recover(service.config, tmp_path / "workspace", config_path).action == "resume"
    start.assert_called_once_with(job.id)


def test_failed_launch_is_not_retried_without_budget_or_in_gateway_process(tmp_path, monkeypatch):
    service, _, config_path = setup(tmp_path)
    service.config.worker_backend = "process"
    start = Mock(side_effect=ValueError("could not start"))
    monkeypatch.setattr(DevelopmentService, "start", start)
    assert recovery.recover(service.config, tmp_path / "workspace", config_path).reason == "independent_worker_service_required"
    start.assert_not_called()
    service.config.worker_backend = "systemd"
    assert recovery.recover(service.config, tmp_path / "workspace", config_path).action == "unavailable"
    assert len(read_state(service.store.root / "recovery.json")["attempts"]) == 1


def test_systemd_launch_is_independent_and_fails_closed(tmp_path, monkeypatch):
    service, job, _ = setup(tmp_path)
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr("nanobot.development.service.subprocess.run", run)
    service.start(job.id)
    argv = run.call_args.args[0]
    assert argv[0] == "systemd-run" and "--service-type=exec" in argv
    assert "--collect" in argv and "--property=KillMode=control-group" in argv
    assert argv[-1] == job.id
    assert "--unit=" + service.worker_unit() in argv
    run.return_value.returncode = 1
    with pytest.raises(ValueError, match="could not start"):
        service.start(job.id)
