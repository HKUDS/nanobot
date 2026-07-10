"""Persistence tests for ``nanobot.cron.service.CronService``.

These tests target the specific failure mode where a corrupt or partially
written ``jobs.json`` would silently turn into an empty job list on the next
start, deleting every scheduled job.  See ``fix(cron): atomic write for
jobs.json + don't silently overwrite corrupt store``.
"""

from __future__ import annotations

import errno
import json
from pathlib import Path
from typing import Callable

import pytest

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronPayload, CronSchedule


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


def _corrupt_store(tmp_path: Path) -> Path:
    store_path = tmp_path / "cron" / "jobs.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text("{not valid json", encoding="utf-8")
    return store_path


def _assert_single_corrupt_backup(store_path: Path) -> None:
    assert not store_path.exists()
    backups = list(store_path.parent.glob("jobs.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not valid json"


def _system_job(job_id: str = "dream") -> CronJob:
    return CronJob(
        id=job_id,
        name="Dream",
        schedule=CronSchedule(kind="cron", expr="0 */2 * * *", tz="UTC"),
        payload=CronPayload(kind="system_event"),
    )


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


def test_atomic_write_ignores_unsupported_directory_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vboxsf-like filesystems can open directories but reject directory fsync."""
    store_path = tmp_path / "cron" / "jobs.json"
    dir_fd = 987654

    def fake_open(path: str, flags: int) -> int:
        assert Path(path) == store_path.parent
        return dir_fd

    def fake_fsync(fd: int) -> None:
        if fd == dir_fd:
            raise OSError(errno.EINVAL, "Invalid argument")

    def fake_close(fd: int) -> None:
        assert fd == dir_fd

    monkeypatch.setattr("os.open", fake_open)
    monkeypatch.setattr("os.fsync", fake_fsync)
    monkeypatch.setattr("os.close", fake_close)

    CronService._atomic_write(store_path, '{"version": 1, "jobs": []}')

    assert store_path.read_text(encoding="utf-8") == '{"version": 1, "jobs": []}'
    assert list(store_path.parent.glob("*.tmp")) == []


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


@pytest.mark.parametrize(
    ("api_name", "call"),
    [
        ("list_jobs", lambda service: service.list_jobs()),
        ("get_job", lambda service: service.get_job("missing")),
        ("status", lambda service: service.status()),
        ("remove_job", lambda service: service.remove_job("missing")),
        ("enable_job", lambda service: service.enable_job("missing", enabled=False)),
        ("update_job", lambda service: service.update_job("missing", name="new name")),
        ("register_system_job", lambda service: service.register_system_job(_system_job())),
    ],
)
def test_public_apis_raise_clear_error_for_unavailable_corrupt_store(
    tmp_path: Path,
    api_name: str,
    call: Callable[[CronService], object],
) -> None:
    """Public APIs should report the corrupt store explicitly instead of
    leaking ``AttributeError`` when the first load cannot produce a store."""
    store_path = _corrupt_store(tmp_path)
    service = CronService(store_path)

    with pytest.raises(RuntimeError, match="corrupt.*restore jobs.json") as exc_info:
        call(service)

    assert api_name
    assert str(store_path) in str(exc_info.value)
    _assert_single_corrupt_backup(store_path)


@pytest.mark.asyncio
async def test_run_job_raises_clear_error_and_restores_running_state_for_corrupt_store(
    tmp_path: Path,
) -> None:
    store_path = _corrupt_store(tmp_path)
    service = CronService(store_path)

    with pytest.raises(RuntimeError, match="corrupt.*restore jobs.json"):
        await service.run_job("missing")

    assert service._running is False
    _assert_single_corrupt_backup(store_path)


@pytest.mark.asyncio
async def test_run_job_preserves_running_state_when_corrupt_store_unavailable(
    tmp_path: Path,
) -> None:
    store_path = _corrupt_store(tmp_path)
    service = CronService(store_path)
    service._running = True
    service._arm_timer = lambda: None

    with pytest.raises(RuntimeError, match="corrupt.*restore jobs.json"):
        await service.run_job("missing")

    assert service._running is True
    service.stop()


def test_running_add_job_raises_clear_error_for_unavailable_corrupt_store(
    tmp_path: Path,
) -> None:
    store_path = _corrupt_store(tmp_path)
    service = CronService(store_path)
    service._running = True

    with pytest.raises(RuntimeError, match="corrupt.*restore jobs.json"):
        service.add_job(
            name="running add",
            schedule=CronSchedule(kind="every", every_ms=60_000),
            message="hello",
            session_key="websocket:chat-1",
            origin_channel="websocket",
            origin_chat_id="chat-1",
        )

    _assert_single_corrupt_backup(store_path)


def test_stopped_add_job_still_appends_action_without_loading_corrupt_store(
    tmp_path: Path,
) -> None:
    """The stopped-service add path is an action-log write and must not start
    requiring a readable store."""
    store_path = _corrupt_store(tmp_path)
    service = CronService(store_path)

    job = service.add_job(
        name="offline add",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
        session_key="websocket:chat-1",
        origin_channel="websocket",
        origin_chat_id="chat-1",
    )

    assert job.name == "offline add"
    assert store_path.exists()
    assert store_path.read_text(encoding="utf-8") == "{not valid json"
    assert list(store_path.parent.glob("jobs.json.corrupt-*")) == []
    actions = (store_path.parent / "action.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(actions) == 1
    assert json.loads(actions[0])["action"] == "add"


def test_public_api_uses_in_memory_snapshot_when_disk_becomes_corrupt(
    tmp_path: Path,
) -> None:
    service, store_path = _seeded_store(tmp_path)
    service._load_store()
    assert service._store is not None
    store_path.write_text("{not valid json", encoding="utf-8")

    jobs = service.list_jobs(include_disabled=True)

    assert len(jobs) == 1
    assert jobs[0].name == "Daily Loving Message"


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
