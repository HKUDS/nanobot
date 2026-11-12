"""Frozen service recovery for one explicitly confirmed update.

Keep this module stdlib-only. A program snapshot is not a data backup: recovery
never restores user stores. Same-filesystem renames retain both program generations.
The caller must hold exclusive installation/data leases before snapshot or restore.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
from contextlib import suppress
from importlib.metadata import distributions
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZipFile

from nanobot.installation_lock import (
    InstallationBusyError,
    file_access,
    installation_access,
    installation_state_dir,
    pending_update_path,
)

if TYPE_CHECKING:
    from nanobot.update_worker import EnvironmentSnapshot, WorkerSpec


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _sync_directory(path: Path) -> None:
    # Windows does not expose POSIX directory fsync through this interface.
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _inspect_metadata(spec: WorkerSpec) -> EnvironmentSnapshot:
    """Read ownership without executing a possibly broken candidate's site hooks."""
    from nanobot.update_worker import EnvironmentSnapshot

    root = Path(spec.baseline.environment)
    sites = [root / "Lib/site-packages"] if os.name == "nt" else list((root / "lib").glob("python*/site-packages"))
    if len(sites) != 1 or not sites[0].is_dir() or sites[0].is_symlink():
        raise ValueError("The selected installation's package location changed")
    items: dict[str, str] = {}
    versions: dict[str, str] = {}
    records: dict[str, str] = {}
    for distribution in distributions(path=[str(sites[0])]):
        raw_name, version = distribution.metadata["Name"], distribution.version
        if not raw_name or not version:
            # Interrupted pip transactions can leave an incomplete dist-info.
            # Missing targets are allowed by check_environment(repairing=True);
            # missing unrelated distributions still fail its baseline comparison.
            continue
        name = re.sub(r"[-_.]+", "-", raw_name).lower()
        payload = "\n".join(distribution.read_text(f) or "" for f in ("METADATA", "RECORD", "direct_url.json"))
        items[name] = hashlib.sha256(payload.encode()).hexdigest()
        versions[name] = version
        if name == "nanobot-ai":
            records = {key: hashlib.sha256((distribution.read_text(key) or "").encode()).hexdigest()
                       for key in ("RECORD", "direct_url.json")}
    return EnvironmentSnapshot(str(root), spec.baseline.python, spec.baseline.base_python,
                               _digest(root / "pyvenv.cfg"), items, versions, versions.get("nanobot-ai", ""), records,
                               _digest(root / "uv-receipt.toml") if (root / "uv-receipt.toml").exists() else None,
                               _digest(root / "nanobot-install.json") if (root / "nanobot-install.json").exists() else None)


def _tree(root: Path) -> dict[str, tuple[str, str, int]]:
    """Hash files and preserve symlinks without following them outside the venv."""
    result: dict[str, tuple[str, str, int]] = {}
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in [*folders, *files]:
            path = Path(directory) / name
            info = path.lstat()
            key = str(path.relative_to(root))
            mode = stat.S_IMODE(info.st_mode)
            if path.is_symlink():
                result[key] = ("link", os.readlink(path), mode)
            elif getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("The program environment contains a redirected directory")
            elif stat.S_ISDIR(info.st_mode):
                result[key] = ("directory", "", mode)
            elif stat.S_ISREG(info.st_mode):
                result[key] = ("file", _digest(path), mode)
            else:
                raise ValueError("The program environment contains a special file; it cannot be preserved safely")
    return result


def _tree_digest(root: Path) -> str:
    return hashlib.sha256(json.dumps(_tree(root), sort_keys=True).encode()).hexdigest()


def _paths(spec: WorkerSpec) -> tuple[Path, Path, Path]:
    environment = Path(spec.baseline.environment)
    # No user-supplied restore destination or recursive deletion. The original
    # venv path remains its identity (and keeps console-script shebangs valid).
    if environment.is_symlink() or environment.parent == environment or environment == Path.home():
        raise ValueError("Invalid program restoration destination")
    return (environment, environment.with_name(f".nanobot-original-{spec.plan_id}"),
            environment.with_name(f".nanobot-failed-{spec.plan_id}"))


def _copy_program_file(source: str, destination: str) -> str:
    shutil.copyfile(source, destination)
    # Windows fsync requires a writable handle. Open it before copystat restores
    # a package file's read-only flag; keep that handle through metadata sync.
    with Path(destination).open("rb+") as stream:
        shutil.copystat(source, destination)
        os.fsync(stream.fileno())
    return destination


def preserve_program(directory: Path, spec: WorkerSpec) -> None:
    from nanobot.update_worker import read_record, write_record

    if not spec.automatic_recovery or spec.uv is not None:
        return
    environment, original, _ = _paths(spec)
    receipt = directory / "program-backup.json"
    if receipt.exists():
        record = read_record(receipt)
        if record.get("request_sha256") != _digest(directory / "request.json") or record.get("sha256") != _tree_digest(original):
            raise ValueError("The original program snapshot changed")
        return
    if original.exists() or original.is_symlink():
        raise ValueError("An incomplete program snapshot already exists; keep it for diagnosis")
    # Refuse nested data: a program-only restoration must never move user data.
    if any(Path(source.path).is_relative_to(environment) and Path(source.path) not in {
        environment / "pyvenv.cfg", environment / "nanobot-install.json",
    } for source in spec.backup_sources):
        raise ValueError("User data is inside the program environment; automatic program restoration is unsafe")
    size = sum(path.stat().st_size for path in environment.rglob("*") if path.is_file() and not path.is_symlink())
    if shutil.disk_usage(environment.parent).free < size + 32 * 1024**2:
        raise ValueError("Not enough space to preserve the original program; no packages were changed")
    before = _tree_digest(environment)
    shutil.copytree(environment, original, symlinks=True, copy_function=_copy_program_file)
    original.chmod(0o700)
    # File copies are durable; flush directory entries before the receipt.
    for root, _, _ in os.walk(original, topdown=False, followlinks=False):
        _sync_directory(Path(root))
    if _tree_digest(original) != before or _tree_digest(environment) != before:
        raise ValueError("The program changed during its snapshot; no packages were changed")
    write_record(receipt, {"plan_id": spec.plan_id, "request_sha256": _digest(directory / "request.json"), "sha256": before})
    _sync_directory(original.parent)


def require_unchanged_user_data(directory: Path, spec: WorkerSpec) -> None:
    """Compare contents, not mtimes; never write a byte to a user store."""
    from nanobot.update_backup import BackupSource, current_file_hashes, verify_backup

    digest = _digest(directory / "request.json")
    archive = verify_backup(directory, spec.backup_sources, digest)
    environment = Path(spec.baseline.environment)
    profiles = installation_state_dir(spec.baseline.environment) / "profiles"
    sources = [Path(source.path) for source in spec.backup_sources
               if not Path(source.path).is_relative_to(environment) and not Path(source.path).is_relative_to(profiles)]
    with ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        expected = {item["path"]: item["sha256"] for item in manifest["entries"]
                    if item["kind"] == "file" and any(Path(item["path"]).is_relative_to(root) for root in sources)}
    actual = current_file_hashes(tuple(BackupSource(str(source)) for source in sources))
    if actual != expected:
        raise ValueError("User data changed after installation; keep the current program and original backup")


def restore_program(directory: Path, spec: WorkerSpec) -> None:
    from nanobot.update_worker import read_record, write_record

    if spec.uv is not None:
        raise ValueError("An external package manager owns this program; automatic downgrade is unavailable")
    environment, original, failed = _paths(spec)
    receipt = read_record(directory / "program-backup.json")
    if receipt.get("plan_id") != spec.plan_id or receipt.get("request_sha256") != _digest(directory / "request.json"):
        raise ValueError("The original program belongs to a different update")
    if not original.exists():
        # A crash after the second rename is a completed restoration, not a
        # reason to snapshot or replace the environment again.
        if failed.is_dir() and _tree_digest(environment) == receipt.get("sha256"):
            write_record(directory / "restoration.json", {"plan_id": spec.plan_id, "state": "restarting"})
            return
        raise ValueError("The original program snapshot is unavailable")
    if original.is_symlink() or _tree_digest(original) != receipt.get("sha256"):
        raise ValueError("The original program snapshot changed")
    write_record(directory / "restoration.json", {"plan_id": spec.plan_id, "state": "restoring"})
    if environment.exists():
        if failed.exists() or failed.is_symlink():
            raise ValueError("A failed program generation already exists; refusing to replace it")
        os.rename(environment, failed)
        _sync_directory(environment.parent)
    os.rename(original, environment)
    _sync_directory(environment.parent)
    # Journal publication follows renames. Both generations remain recoverable.
    write_record(directory / "restoration.json", {"plan_id": spec.plan_id, "state": "restarting"})


def _shutdown_committed(spec: WorkerSpec) -> bool:
    from nanobot.update_worker import read_record

    try:
        stop = read_record(installation_state_dir(spec.baseline.environment) / "stop.json")
    except FileNotFoundError:
        return False
    return stop.get("plan_id") == spec.plan_id and stop.get("phase") in {"commit", "stopped"}


def restore_service(directory: Path, *, confirmation_id: str | None = None) -> None:
    from nanobot.update_worker import (
        JobStatus,
        Phase,
        WorkerSpec,
        check_approval,
        check_environment,
        read_record,
        require_pending_owner,
        restart_runtime,
        write_record,
    )

    spec = WorkerSpec.read(directory)
    root = installation_state_dir(spec.baseline.environment)
    with file_access(root / "worker.lock", exclusive=True):
        status = JobStatus.read(directory)
        if status.phase in {Phase.SUCCEEDED, Phase.RESTORED, Phase.CANCELLED}:
            return
        restoration_path = directory / "restoration.json"
        if restoration_path.exists():
            restoration = read_record(restoration_path)
            if (restoration == {"plan_id": spec.plan_id, "state": "restarting"}
                    and status.phase in {Phase.RESTARTING, Phase.ACTIVATING, Phase.FINALIZING, Phase.RESTART_FAILED}):
                # Program restoration already committed. Resume only its runtime
                # handoff, including cleanup after old-version activation.
                if confirmation_id is not None:
                    check_approval(directory, spec, handoff=True, confirmation_id=confirmation_id, check_expiry=False)
                restart_runtime(directory, spec)
                return
            if restoration not in ({"plan_id": spec.plan_id, "state": "restoring"},
                                   {"plan_id": spec.plan_id, "state": "restarting"}):
                raise ValueError("Invalid original-program restoration journal")
        # Durable activation can mean the new runtime has accepted tasks. Never
        # downgrade or roll data back after that point.
        if (directory / "activation.json").exists():
            raise ValueError("The new runtime was activated; only same-version repair is safe")
        check_approval(directory, spec, handoff=True, confirmation_id=confirmation_id, check_expiry=False)
        if not _shutdown_committed(spec):
            if not status.mutation_started:
                status.advance(directory, Phase.HANDOFF_FAILED, "Shutdown was not committed; review the update again", mutation_started=False)
            return  # A refused preflight left the original service running.
        with file_access(root / "handoff-child.lock", exclusive=True):
            pass
        restoring = restoration_path.exists()
        with spec.mutation_access() as (_, data):
            require_pending_owner(spec)
            if not restoring or not status.mutation_started:
                check_environment(spec, repairing=status.mutation_started, current=_inspect_metadata(spec))
            if status.mutation_started:
                require_unchanged_user_data(directory, spec)
                restore_program(directory, spec)
            else:
                write_record(directory / "restoration.json", {"plan_id": spec.plan_id, "state": "restarting"})
            data.reserve()
            pending = pending_update_path(spec.baseline.environment)
            pending.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_record(pending, {
                "schema_version": 2, "job_id": spec.plan_id, "version": spec.baseline.app_version,
            })
            status.advance(directory, Phase.RESTARTING, "Restoring the original service without changing user data")
        restart_runtime(directory, spec)


def supervise(directory: Path, arguments: list[str]) -> None:
    """One child execution, one exact-target repair, then safe program restoration."""
    from nanobot.update_worker import (
        JobStatus,
        Phase,
        WorkerSpec,
        check_approval,
        read_record,
        write_record,
    )

    spec = WorkerSpec.read(directory)
    if not spec.automatic_recovery or not spec.restart_profiles:
        raise ValueError("This job did not prepare automatic service recovery")
    with file_access(installation_state_dir(spec.baseline.environment) / "supervisor.lock", exclusive=True):
        journal = directory / "supervision.json"
        confirmation = arguments[2] if len(arguments) == 3 and arguments[0] == "--confirmed-handoff" else None
        if journal.exists():
            previous = read_record(journal)
            if confirmation is None or previous.get("confirmation_id") == confirmation:
                return  # Duplicate/delayed launch is not another recovery budget.
        # Validate even the first journal publication: a delayed launcher may
        # have been replaced before any supervisor acquired this lease.
        if confirmation is not None:
            check_approval(directory, spec, handoff=True, confirmation_id=confirmation)
        write_record(journal, {"plan_id": spec.plan_id, "confirmation_id": confirmation, "started_at": int(time.time())})
        command = [spec.baseline.base_python, "-I", "-S", str(directory / "worker.pyz")]
        try:
            subprocess.run([*command, *arguments], check=False, timeout=1800)
        except subprocess.TimeoutExpired:
            pass  # Orphan children still own leases; recovery cannot race them.
        status = JobStatus.read(directory)
        if status.phase in {Phase.SUCCEEDED, Phase.RESTORED, Phase.CANCELLED}:
            if status.phase == Phase.SUCCEEDED:
                _discard_program_snapshot(directory, spec)
            return
        if (status.phase == Phase.HANDOFF_FAILED and not status.mutation_started
                and not _shutdown_committed(spec)):
            # A busy gateway correctly refused shutdown and retains its runtime
            # lease. Waiting for that lease would hide the refusal for five minutes.
            return
        if confirmation is not None:
            check_approval(directory, spec, handoff=True, confirmation_id=confirmation, check_expiry=False)
        # Retry only admitted work. No second stop request, download or release
        # resolution. Lease-owning orphan children must finish before recovery.
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and not (directory / "activation.json").exists():
            try:
                with (installation_access(updating=True, environment=spec.baseline.environment),
                      file_access(installation_state_dir(spec.baseline.environment) / "handoff-child.lock", exclusive=True)):
                    break
            except (InstallationBusyError, BlockingIOError):
                time.sleep(0.2)
        if (directory / "approval.json").exists() and not (directory / "restoration.json").exists():
            try:
                subprocess.run([*command, "--recover", str(directory)], check=False, timeout=1800)
            except subprocess.TimeoutExpired:
                pass
            if JobStatus.read(directory).phase == Phase.SUCCEEDED:
                _discard_program_snapshot(directory, spec)
                return
        try:
            try:
                restore_service(directory, confirmation_id=confirmation)
            except OSError:
                # A transient filesystem error between the two renames must
                # not leave an absent venv. Replay the journal once, retaining
                # the same snapshot, ownership checks and recovery budget.
                restore_service(directory, confirmation_id=confirmation)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            # Keep fences, snapshots and the exact failure state. A hardware,
            # ownership or changed-data failure is not permission to discard data.
            status = JobStatus.read(directory)
            status.advance(directory, status.phase,
                           "Automatic recovery could not safely finish; original backup and program generations are retained")
            write_record(journal, {"plan_id": spec.plan_id, "confirmation_id": confirmation, "state": "needs_attention"})


def _discard_program_snapshot(directory: Path, spec: WorkerSpec) -> None:
    """Remove only this successful job's redundant program copy, never its data backup."""
    from nanobot.update_worker import read_record

    _, original, _ = _paths(spec)
    # Cleanup is not part of gateway readiness. Failed cleanup retains evidence
    # and must not turn an already usable update into another recovery attempt.
    with suppress(OSError, ValueError):
        record = read_record(directory / "program-backup.json")
        if (not original.is_symlink() and record.get("plan_id") == spec.plan_id
                and original.is_dir() and _tree_digest(original) == record.get("sha256")):
            shutil.rmtree(original)
            _sync_directory(original.parent)
