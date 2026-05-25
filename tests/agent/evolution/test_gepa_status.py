"""Tests for GEPA run status persistence."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from nanobot.agent.evolution.gepa_status import (
    GEPA_SKIP_ALREADY_RUNNING,
    GepaRunLock,
    GepaRunStatus,
    GepaRunStore,
)


def test_gepa_run_store_round_trip(tmp_path) -> None:
    store = GepaRunStore(tmp_path)
    status = GepaRunStatus(
        run_id="run-123",
        trigger="cron",
        skill_name="deploy-k8s",
        phase="optimizing",
        message="optimizing deploy-k8s",
        started_at="2026-05-24T10:00:00+00:00",
        finished_at="",
        proposals_created=("prop-a", "prop-b"),
        traces_consumed=("trace-1", "trace-2"),
        budget_usd_spent=1.25,
        error="",
    )

    store.save(status)
    loaded = store.get()

    assert loaded == status
    assert store.path.exists()
    on_disk = json.loads(store.path.read_text(encoding="utf-8"))
    assert on_disk["phase"] == "optimizing"
    assert on_disk["proposals_created"] == ["prop-a", "prop-b"]


def test_gepa_run_store_missing_file_returns_idle(tmp_path) -> None:
    store = GepaRunStore(tmp_path)

    status = store.get()

    assert status == GepaRunStatus.idle()
    assert status.phase == "idle"


def test_gepa_run_store_invalid_json_returns_idle(tmp_path) -> None:
    store = GepaRunStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json", encoding="utf-8")

    status = store.get()

    assert status == GepaRunStatus.idle()


def test_gepa_run_store_non_object_json_returns_idle(tmp_path) -> None:
    store = GepaRunStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("[1, 2, 3]", encoding="utf-8")

    status = store.get()

    assert status == GepaRunStatus.idle()


def test_gepa_run_status_from_dict_tolerates_partial_and_invalid_fields() -> None:
    status = GepaRunStatus.from_dict(
        {
            "run_id": "abc",
            "trigger": "not-a-trigger",
            "phase": "not-a-phase",
            "proposals_created": "bad",
            "budget_usd_spent": "nope",
        }
    )

    assert status.run_id == "abc"
    assert status.trigger is None
    assert status.phase == "idle"
    assert status.proposals_created == ()
    assert status.budget_usd_spent == 0.0


def test_gepa_run_status_with_updates() -> None:
    idle = GepaRunStatus.idle()
    running = idle.with_updates(
        run_id="run-1",
        trigger="slash",
        phase="starting",
        message="acquiring lock",
    )

    assert running.run_id == "run-1"
    assert running.trigger == "slash"
    assert running.phase == "starting"
    assert running.message == "acquiring lock"
    assert idle.phase == "idle"


def test_gepa_run_lock_blocks_second_holder_until_release(tmp_path) -> None:
    first = GepaRunLock(tmp_path)
    second = GepaRunLock(tmp_path)

    assert first.try_acquire_run_lock() is True
    assert second.try_acquire_run_lock() is False

    first.release_run_lock()
    assert second.try_acquire_run_lock() is True
    second.release_run_lock()


def test_gepa_run_lock_cross_process_single_flight(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    child_code = textwrap.dedent(
        f"""
        import sys
        import time
        from pathlib import Path

        sys.path.insert(0, {str(repo_root)!r})
        from nanobot.agent.evolution.gepa_status import GepaRunLock

        lock = GepaRunLock(Path({str(tmp_path)!r}))
        assert lock.try_acquire_run_lock()
        time.sleep(2)
        lock.release_run_lock()
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", child_code],
        cwd=str(repo_root),
    )
    try:
        time.sleep(0.3)
        peer = GepaRunLock(tmp_path)
        assert peer.try_acquire_run_lock() is False

        assert proc.wait(timeout=10) == 0
        assert peer.try_acquire_run_lock() is True
        peer.release_run_lock()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_gepa_skip_already_running_constant() -> None:
    assert GEPA_SKIP_ALREADY_RUNNING == "already running"
