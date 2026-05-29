"""Persistence tests for ``nanobot.cron.service.CronService``.

These tests target the specific failure mode where a corrupt or partially
written ``jobs.json`` would silently turn into an empty job list on the next
start, deleting every scheduled job.  See ``fix(cron): atomic write for
jobs.json + don't silently overwrite corrupt store``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule


def _seeded_store(tmp_path: Path) -> tuple[CronService, Path]:
    """Build a service with one persisted job on disk and return both the
    service and the resolved store path.  Adds the job via the action log
    (the path used when the service is not running) and then triggers a
    merge so ``jobs.json`` is written, mirroring the persisted on-disk
    state seen in production."""
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path)
    service.add_job(
        name="Daily Loving Message",
        schedule=CronSchedule(kind="cron", expr="0 10 * * *", tz="Asia/Kuwait"),
        message="hello",
    )
    # add_job appended to action.jsonl; flush to jobs.json by toggling
    # ``_running`` long enough for ``_merge_action`` to do its rewrite.
    service._running = True
    try:
        service._load_store()
    finally:
        service._running = False
    assert store_path.exists()
    return service, store_path


def test_save_store_is_atomic(tmp_path: Path) -> None:
    """``_save_store`` must use temp-file + rename so an interrupted write
    cannot leave the destination truncated or invalid."""
    service, store_path = _seeded_store(tmp_path)

    # Simulate an arbitrary save and confirm the result parses cleanly and
    # no orphan ``.tmp`` is left behind.
    service._save_store()
    data = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(data["jobs"]) == 1

    tmp_files = list(store_path.parent.glob("*.tmp"))
    assert tmp_files == [], f"unexpected temp files left behind: {tmp_files}"


def test_save_store_failure_does_not_corrupt_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If writing the temp file blows up partway through, the previous
    ``jobs.json`` must remain readable.  This is the regression we are
    actually fixing: pre-fix, ``write_text`` would truncate the destination
    in place and leave it corrupt."""
    service, store_path = _seeded_store(tmp_path)
    original = store_path.read_bytes()

    # Inject a failure inside the temp-file write.  ``os.replace`` should
    # never run; the destination must keep its previous content.
    real_open = open

    def boom(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(path).endswith(".tmp"):
            raise OSError("simulated disk full")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", boom)

    with pytest.raises(OSError, match="simulated disk full"):
        service._save_store()

    assert store_path.read_bytes() == original


def test_load_jobs_preserves_corrupt_store_and_returns_none(
    tmp_path: Path,
) -> None:
    """A corrupt ``jobs.json`` must not be silently treated as an empty
    list.  The loader returns ``None`` and the corrupt file is moved aside
    with a ``.corrupt-<ts>`` suffix so an operator can recover it."""
    store_path = tmp_path / "cron" / "jobs.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text("{not valid json", encoding="utf-8")

    service = CronService(store_path)
    assert service._load_jobs() is None

    # Original path is gone; a ``.corrupt-<ts>`` backup exists alongside it.
    assert not store_path.exists()
    backups = list(store_path.parent.glob("jobs.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not valid json"


def test_start_refuses_to_overwrite_corrupt_store(tmp_path: Path) -> None:
    """``start`` must abort instead of running ``_save_store`` against an
    empty in-memory state when the on-disk store is corrupt.  Otherwise the
    next save would overwrite the (recoverable) corrupt file with an empty
    job list and the user's jobs would be unrecoverable."""
    store_path = tmp_path / "cron" / "jobs.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text("{still not json", encoding="utf-8")

    service = CronService(store_path)
    import asyncio

    with pytest.raises(RuntimeError, match="corrupt"):
        asyncio.run(service.start())

    # Service is left in a stopped state so the operator notices.
    assert service._running is False

    # And the corrupt file is still recoverable from the .corrupt-<ts> copy.
    backups = list(store_path.parent.glob("jobs.json.corrupt-*"))
    assert len(backups) == 1


def test_load_store_falls_back_to_in_memory_on_corruption_after_start(
    tmp_path: Path,
) -> None:
    """If the store file becomes corrupt *after* a successful start (e.g. a
    rclone-mounted Drive returns a partial read), the service must keep
    using its existing in-memory snapshot instead of dropping every job."""
    service, store_path = _seeded_store(tmp_path)
    # Force load so ``self._store`` is populated.
    service._load_store()
    snapshot = service._store
    assert snapshot is not None and len(snapshot.jobs) == 1

    # Now corrupt the file on disk.
    store_path.write_text("\x00garbage\x00", encoding="utf-8")

    # Subsequent reload returns the in-memory snapshot, not None or empty.
    result = service._load_store()
    assert result is snapshot
    assert len(result.jobs) == 1
    assert result.jobs[0].name == "Daily Loving Message"


def test_full_round_trip_survives_repeated_save_load(tmp_path: Path) -> None:
    """Sanity check: jobs survive add → save → reload across fresh
    ``CronService`` instances pointing at the same store."""
    store_path = tmp_path / "cron" / "jobs.json"

    s1 = CronService(store_path)
    s1.add_job(
        name="Daily Loving Message",
        schedule=CronSchedule(kind="cron", expr="0 10 * * *", tz="Asia/Kuwait"),
        message="hello",
    )

    s2 = CronService(store_path)
    s2._load_store()
    assert s2._store is not None
    assert [j.name for j in s2._store.jobs] == ["Daily Loving Message"]
