"""Tests for cron job persistence across service restarts.

Verifies the fix for https://github.com/HKUDS/nanobot/issues/268:
container restarts must not erase existing jobs from jobs.json.
"""

import asyncio
import json
from pathlib import Path
from typing import Generator

import pytest

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store_data(jobs: list[dict] | None = None) -> dict:
    """Build a valid jobs.json payload."""
    return {
        "version": 1,
        "jobs": jobs or [],
    }


def _sample_job(
    job_id: str = "abc123",
    name: str = "test-job",
    kind: str = "every",
    every_ms: int = 60_000,
) -> dict:
    """Return a single serialised job dict (as stored on disk)."""
    return {
        "id": job_id,
        "name": name,
        "enabled": True,
        "schedule": {
            "kind": kind,
            "atMs": None,
            "everyMs": every_ms,
            "expr": None,
            "tz": None,
        },
        "payload": {
            "kind": "agent_turn",
            "message": "hello from cron",
            "deliver": False,
            "channel": None,
            "to": None,
        },
        "state": {
            "nextRunAtMs": None,
            "lastRunAtMs": None,
            "lastStatus": None,
            "lastError": None,
        },
        "createdAtMs": 1700000000000,
        "updatedAtMs": 1700000000000,
        "deleteAfterRun": False,
    }


def _write_store(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _read_store(path: Path) -> dict:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCronPersistence:
    """Jobs written to jobs.json must survive service restart."""

    def test_existing_jobs_preserved_after_restart(self, tmp_path: Path) -> None:
        """Core regression test for #268: pre-existing jobs must not be wiped."""
        store_path = tmp_path / "cron" / "jobs.json"
        job = _sample_job()
        _write_store(store_path, _make_store_data([job]))

        # Simulate first boot → stop → second boot
        svc = CronService(store_path)
        asyncio.get_event_loop().run_until_complete(svc.start())
        svc.stop()

        # Create a *new* service instance (simulates container restart)
        svc2 = CronService(store_path)
        asyncio.get_event_loop().run_until_complete(svc2.start())
        svc2.stop()

        # The on-disk file must still contain our job
        data = _read_store(store_path)
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["id"] == job["id"]
        assert data["jobs"][0]["name"] == job["name"]

    def test_no_store_file_creates_empty(self, tmp_path: Path) -> None:
        """When no jobs.json exists, the service creates a fresh empty one."""
        store_path = tmp_path / "cron" / "jobs.json"
        assert not store_path.exists()

        svc = CronService(store_path)
        asyncio.get_event_loop().run_until_complete(svc.start())
        svc.stop()

        assert store_path.exists()
        data = _read_store(store_path)
        assert data["jobs"] == []

    def test_empty_store_file_loads_without_error(self, tmp_path: Path) -> None:
        """An existing but empty jobs list should not cause errors."""
        store_path = tmp_path / "cron" / "jobs.json"
        _write_store(store_path, _make_store_data([]))

        svc = CronService(store_path)
        asyncio.get_event_loop().run_until_complete(svc.start())
        svc.stop()

        data = _read_store(store_path)
        assert data["jobs"] == []

    def test_multiple_jobs_preserved(self, tmp_path: Path) -> None:
        """Multiple jobs survive restart."""
        store_path = tmp_path / "cron" / "jobs.json"
        jobs = [
            _sample_job("job-1", "first"),
            _sample_job("job-2", "second"),
            _sample_job("job-3", "third"),
        ]
        _write_store(store_path, _make_store_data(jobs))

        svc = CronService(store_path)
        asyncio.get_event_loop().run_until_complete(svc.start())
        svc.stop()

        svc2 = CronService(store_path)
        asyncio.get_event_loop().run_until_complete(svc2.start())
        svc2.stop()

        data = _read_store(store_path)
        assert len(data["jobs"]) == 3
        ids = {j["id"] for j in data["jobs"]}
        assert ids == {"job-1", "job-2", "job-3"}

    def test_corrupt_json_does_not_overwrite_file(self, tmp_path: Path) -> None:
        """If jobs.json is corrupt, the original file must NOT be overwritten."""
        store_path = tmp_path / "cron" / "jobs.json"
        corrupt_content = "{invalid json!!"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(corrupt_content)

        svc = CronService(store_path)
        asyncio.get_event_loop().run_until_complete(svc.start())
        svc.stop()

        # The service should start with 0 jobs in memory but the corrupt
        # file on disk must be preserved for user inspection.
        assert svc.status()["jobs"] == 0
        # File should still contain the original corrupt content
        assert store_path.read_text() == corrupt_content

    def test_force_reload_picks_up_disk_changes(self, tmp_path: Path) -> None:
        """start() must re-read from disk even if the store was cached."""
        store_path = tmp_path / "cron" / "jobs.json"
        _write_store(store_path, _make_store_data([]))

        svc = CronService(store_path)
        # Prime the cache with empty store
        svc.status()
        assert svc.status()["jobs"] == 0

        # Externally add a job (simulates editing while container was stopped)
        _write_store(store_path, _make_store_data([_sample_job()]))

        # start() should force-reload and find the new job
        asyncio.get_event_loop().run_until_complete(svc.start())
        assert svc.status()["jobs"] == 1
        svc.stop()

    def test_jobs_added_while_stopped_are_loaded(self, tmp_path: Path) -> None:
        """Exact reproduction of issue #268 scenario."""
        store_path = tmp_path / "cron" / "jobs.json"

        # 1. Start service (no jobs)
        svc = CronService(store_path)
        asyncio.get_event_loop().run_until_complete(svc.start())
        svc.stop()

        # 2. While stopped, user edits jobs.json to add a job
        _write_store(store_path, _make_store_data([
            _sample_job("manual-1", "user-added-job"),
        ]))

        # 3. Restart service (new instance, simulating container restart)
        svc2 = CronService(store_path)
        asyncio.get_event_loop().run_until_complete(svc2.start())

        # Must have picked up the manually-added job
        assert svc2.status()["jobs"] == 1
        jobs = svc2.list_jobs(include_disabled=True)
        assert len(jobs) == 1
        assert jobs[0].id == "manual-1"
        assert jobs[0].name == "user-added-job"
        svc2.stop()

        # And the file on disk still has it
        data = _read_store(store_path)
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["id"] == "manual-1"
