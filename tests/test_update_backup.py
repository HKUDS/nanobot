"""Scoped snapshots preserve real data and never silently expand read authority."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from nanobot import update_backup
from nanobot.data_access import profile_data_paths
from nanobot.update_backup import (
    BackupSource,
    ensure_backup,
    unique_sources,
    verify_backup,
)


@pytest.fixture
def scoped_data(tmp_path):
    home, data, workspace, job = (tmp_path / name for name in ("home", "config data", "user project", "job"))
    for path in (home, data, workspace, job):
        path.mkdir()
    files = {
        data / "custom.json": '{"credential":"private fixture"}',
        data / "sessions/workspace/session.jsonl": '{"content":"original conversation"}\n',
        data / "webui/transcript.jsonl": '{"content":"UI history"}\n',
        data / "media/image.txt": "fixture attachment",
        data / "auth/mcp.json": '{"fixture":"secret"}',
        data / "cli-apps/installed.json": '{"apps":[]}',
        workspace / "memory/history.jsonl": '{"memory":"original"}\n',
        workspace / ".nanobot/workspace-id": "namespace",
        workspace / "cron/jobs.json": '{"jobs":[]}',
        workspace / "skills/custom/SKILL.md": "user skill",
        home / "sessions/legacy.jsonl": "legacy conversation",
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    # Paths intentionally excluded: arbitrary project data and installed binaries.
    for path in (workspace / "src/private.py", data / "bin/cua", data / "logs/runtime.log",
                 data / "cli-apps/venvs/application/binary"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not part of this backup")
    paths = profile_data_paths(home=home, data_dir=data, config=data / "custom.json", workspace=workspace)
    sources = unique_sources([BackupSource(str(path)) for path in paths])
    return job, sources, files


def test_complete_private_snapshot_contains_only_owned_stores_and_keeps_original(scoped_data):
    job, sources, files = scoped_data
    archive = ensure_backup(job, sources, "a" * 64, mutated=False)
    with ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        entries = {entry["path"]: entry for entry in manifest["entries"]}
        assert {path for path, entry in entries.items() if entry["kind"] == "file"} == {str(path) for path in files}
        for path, content in files.items():
            entry = entries[str(path)]
            actual = bundle.read(entry["member"])
            assert actual == content.encode()
            assert hashlib.sha256(actual).hexdigest() == entry["sha256"]
        assert any(item["kind"] == "missing" for item in entries.values())
    original = archive.read_bytes()
    next(iter(files)).write_text("changed after installation or migration")
    with pytest.raises(ValueError, match="before installation"):
        ensure_backup(job, sources, "a" * 64, mutated=False)
    assert ensure_backup(job, sources, "a" * 64, mutated=True) == archive
    assert archive.read_bytes() == original
    assert verify_backup(job, sources, "a" * 64) == archive
    if os.name != "nt":
        assert archive.stat().st_mode & 0o777 == 0o600
        assert archive.parent.stat().st_mode & 0o777 == 0o700
        assert (archive.parent / "receipt.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="different update"):
        verify_backup(job, sources, "b" * 64)


@pytest.mark.skipif(os.name == "nt", reason="Symlink creation requires separate Windows privileges")
def test_backup_refuses_external_symlink_and_special_file(scoped_data, tmp_path):
    job, sources, files = scoped_data
    memory = next(path.parent for path in files if path.name == "history.jsonl")
    external = tmp_path / "unrelated-private-file"
    external.write_text("not authorized by the selected scope")
    link = memory / "external"
    link.symlink_to(external)
    with pytest.raises(ValueError, match="symlink"):
        ensure_backup(job, sources, "a" * 64, mutated=False)
    assert not (job / "backup").exists()
    link.unlink()
    os.mkfifo(link)
    with pytest.raises(ValueError, match="special file"):
        ensure_backup(job, sources, "a" * 64, mutated=False)
    assert not (job / "backup").exists()


def test_backup_failure_keeps_incomplete_attempt_and_retries_without_false_completion(scoped_data, monkeypatch):
    job, sources, files = scoped_data
    original_inventory = update_backup._inventory
    calls = 0

    def change_during_copy(scope):
        nonlocal calls
        calls += 1
        if calls == 2:
            next(iter(files)).write_text("concurrent writer changed data")
        return original_inventory(scope)

    with monkeypatch.context() as patch:
        patch.setattr(update_backup, "_inventory", change_during_copy)
        with pytest.raises(ValueError, match="changed during backup"):
            ensure_backup(job, sources, "a" * 64, mutated=False)
    assert not (job / "backup").exists()
    assert len(list(job.glob(".backup-*"))) == 1
    archive = ensure_backup(job, sources, "a" * 64, mutated=False)
    assert archive.exists()
    assert len(list(job.glob(".backup-*"))) == 1  # Do not delete previous recovery material.
    archive.write_bytes(archive.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="missing or changed"):
        ensure_backup(job, sources, "a" * 64, mutated=True)


def test_no_space_and_missing_original_backup_block_before_snapshot(scoped_data, monkeypatch):
    job, sources, _ = scoped_data
    monkeypatch.setattr(update_backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="Not enough space"):
        ensure_backup(job, sources, "a" * 64, mutated=False)
    assert not list(job.iterdir())
    with pytest.raises(ValueError, match="already changed data"):
        ensure_backup(job, sources, "a" * 64, mutated=True)


def test_scheduled_delivery_is_backed_up_and_changes_block_program_rollback(tmp_path):
    from nanobot.bus.delivery import DeliveryRequest
    from nanobot.bus.events import OutboundMessage
    from nanobot.channels.outbox import DeliveryOutbox

    data, job = tmp_path / "data", tmp_path / "job"
    job.mkdir()
    outbox = DeliveryOutbox(data / "delivery/outbox.sqlite3")
    message = OutboundMessage("whatsapp", "chat", "undelivered scheduled result",
                              delivery=DeliveryRequest("run", "whatsapp:chat", None))
    outbox.record(message)
    sources = unique_sources([BackupSource(str(path)) for path in profile_data_paths(
        home=tmp_path / "home", data_dir=data, config=data / "config.json", workspace=tmp_path / "workspace",
    )])
    archive = ensure_backup(job, sources, "a" * 64, mutated=False)
    with ZipFile(archive) as bundle:
        entry = next(item for item in json.loads(bundle.read("manifest.json"))["entries"]
                     if item["path"] == str(outbox.path))
        saved = bundle.read(entry["member"])
    assert saved == outbox.path.read_bytes()
    copied = tmp_path / "retained-outbox.sqlite3"
    copied.write_bytes(saved)
    assert DeliveryOutbox(copied).ready()[0].content == message.content
    outbox.finish(message, "sent")
    with pytest.raises(ValueError, match="changed"):
        verify_backup(job, sources, "a" * 64, unchanged=True)
    assert outbox.ready() == []  # Never replace the live store with the old backup.


def test_scope_cannot_include_its_own_job(tmp_path):
    job = tmp_path / "sessions/job"
    job.mkdir(parents=True)
    with pytest.raises(ValueError, match="job itself"):
        ensure_backup(job, (BackupSource(str(tmp_path / "sessions")),), "a" * 64, mutated=False)


async def test_scoped_backup_reopens_sqlite_history_after_runtime_drain(tmp_path):
    from nanobot.session.manager import SessionManager

    data, workspace, job = (tmp_path / name for name in ("data", "workspace", "job"))
    job.mkdir()
    manager = SessionManager(workspace, sessions_root=data / "sessions")
    session = manager.get_or_create("cli:backup")
    session.add_message("user", "original conversation")
    manager.save(session)
    await manager.state.aclose()

    sources = unique_sources([BackupSource(str(path)) for path in profile_data_paths(
        home=tmp_path / "home", data_dir=data, config=data / "config.json", workspace=workspace,
    )])
    archive = ensure_backup(job, sources, "a" * 64, mutated=False)
    restored_root = tmp_path / "restored-sessions"
    # Reopen the real database from the scoped archive, not a JSONL stand-in.
    with ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        for entry in manifest["entries"]:
            source = Path(entry["path"])
            if entry["kind"] != "file" or not source.is_relative_to(data / "sessions"):
                continue
            target = restored_root / source.relative_to(data / "sessions")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(entry["member"]))
    restored = SessionManager(workspace, sessions_root=restored_root)
    try:
        snapshot = restored.read_session_snapshot("cli:backup")
        assert snapshot is not None
        assert snapshot.messages[0]["content"] == "original conversation"
        assert verify_backup(job, sources, "a" * 64, unchanged=True) == archive
    finally:
        await restored.state.aclose()
