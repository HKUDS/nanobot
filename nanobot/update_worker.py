"""Standalone, offline installer worker for an already prepared update.

This file and its stdlib-only helpers are copied to an immutable zipapp outside
site-packages before mutation. The coordinator uses the base Python. Its installer and
verification children own their runtime leases, so coordinator loss cannot release a
lease while they are still using the installation. Only lease-protected child entrypoints
import the installed nanobot runtime for shutdown, verification or restart.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from email.parser import BytesParser
from enum import Enum
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4
from zipfile import ZipFile

from nanobot.data_access import DataLease, data_access
from nanobot.installation_lock import (
    FileLease,
    InstallationBusyError,
    file_access,
    installation_access,
    installation_state_dir,
    pending_update_path,
)
from nanobot.update_backup import BackupSource, ensure_backup, verify_backup
from nanobot.update_process import (
    PreparationProcess,
    child_leases,
    initialize_runtime,
    inspect_python_environment,
    run_preparation_child,
)
from nanobot.update_uv import UVPreparation, uv_environment
from nanobot.utils.atomic_file import atomic_write_lines, io_path, read_atomic_bytes

_REQUEST_SCHEMA_VERSION = 4
_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_HANDOFF_PROTOCOL = 1

_PROBE = """
import hashlib, json, re, sys
from pathlib import Path
from importlib.metadata import distributions, distribution, PackageNotFoundError
root = Path(sys.prefix).resolve()
cfg = root / 'pyvenv.cfg'
if sys.prefix == sys.base_prefix or not cfg.is_file():
    raise SystemExit('A dedicated virtual environment is required')
owners = [name for name in ('uv-receipt.toml', 'pipx_metadata.json') if (root / name).exists()]
if owners != (['uv-receipt.toml'] if manager == 'uv' else []):
    raise SystemExit('This environment belongs to another package manager')
if 'include-system-site-packages = true' in cfg.read_text().lower():
    raise SystemExit('Shared system packages are not supported by this worker')
items, versions = {}, {}
for d in distributions():
    name = re.sub(r'[-_.]+', '-', d.metadata['Name']).lower()
    payload = '\\n'.join(d.read_text(f) or '' for f in ('METADATA', 'RECORD', 'direct_url.json'))
    items[name] = hashlib.sha256(payload.encode()).hexdigest()
    versions[name] = d.version
try:
    app = distribution('nanobot-ai')
    app_version = app.version
    app_records = {name: hashlib.sha256((app.read_text(name) or '').encode()).hexdigest()
                   for name in ('RECORD', 'direct_url.json')}
except PackageNotFoundError:
    app_version, app_records = '', {}
snapshot = dict(environment=str(root), python=str(Path(sys.executable).absolute()),
    base_python=str(Path(sys._base_executable).resolve()),
    receipt_sha=hashlib.sha256(cfg.read_bytes()).hexdigest(), distributions=items, versions=versions,
    app_version=app_version, app_records=app_records,
    installer_receipt_sha=hashlib.sha256((root / 'nanobot-install.json').read_bytes()).hexdigest()
        if (root / 'nanobot-install.json').is_file() else None,
    manager_receipt_sha=hashlib.sha256((root / owners[0]).read_bytes()).hexdigest() if owners else None)
"""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    data = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in data):
        raise ValueError("Expected string record keys")
    return cast(dict[str, object], data)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError("Expected a bounded nonempty string")
    return value


def _sha(value: object) -> str:
    text = _text(value)
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError("Invalid checksum")
    return text


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer")
    return value


def read_record(path: Path, *, max_bytes: int = 1024 * 1024) -> dict[str, object]:
    path = io_path(path)
    if path.is_symlink():
        raise ValueError("Invalid update record")
    data = read_atomic_bytes(path, max_bytes=max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Update record exceeds its size limit")
    return _object(json.loads(data))


def write_record(path: Path, record: object, *, max_bytes: int = 1024 * 1024) -> None:
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) + 1 > max_bytes:
        raise ValueError("Update record exceeds its size limit")
    atomic_write_lines(path, [encoded])
    io_path(path).chmod(0o600)


def verify_target_handoff(wheel: ZipFile) -> None:
    """Read the target's declared restart contract without executing its code.

    Protocol 1 covers request schema 4, protected -I -S gateway startup, scoped
    data grants and exact-run activation. A matching package version or Python
    filename does not establish that contract. See docs/releasing.md.
    """
    message = ("This release cannot use this updater's protected restart. "
               "Use the installation owner's external update procedure instead.")
    try:
        wheel.getinfo("nanobot/update_restart.py")
        entry = wheel.getinfo("nanobot/update_contract.json")
        if entry.file_size > 4096:
            raise ValueError(message)
        record = _object(json.loads(wheel.read(entry)))
    except (KeyError, ValueError, UnicodeError) as exc:
        raise ValueError(message) from exc
    protocols = record.get("handoff_protocols")
    if (type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or not isinstance(protocols, list)):
        raise ValueError(message)
    values = cast(list[object], protocols)
    if (not 1 <= len(values) <= 32 or not all(type(value) is int and value > 0 for value in values)
            or _HANDOFF_PROTOCOL not in values):
        raise ValueError(message)


@dataclass(frozen=True)
class EnvironmentSnapshot:
    environment: str
    python: str
    base_python: str
    receipt_sha: str
    distributions: dict[str, str]
    versions: dict[str, str]
    app_version: str
    app_records: dict[str, str]
    manager_receipt_sha: str | None = None
    installer_receipt_sha: str | None = None

    @classmethod
    def parse(cls, value: object) -> EnvironmentSnapshot:
        data = _object(value)
        version = data["app_version"]
        if not isinstance(version, str):
            raise ValueError("Invalid installed version")
        return cls(_text(data["environment"]), _text(data["python"]), _text(data["base_python"]),
                   _sha(data["receipt_sha"]), {name: _sha(digest) for name, digest in
                                             _object(data["distributions"]).items()},
                   {name: _text(value) for name, value in _object(data["versions"]).items()}, version,
                   {name: _sha(digest) for name, digest in _object(data["app_records"]).items()},
                   _sha(data["manager_receipt_sha"]) if data.get("manager_receipt_sha") is not None else None,
                   _sha(data["installer_receipt_sha"]) if data.get("installer_receipt_sha") is not None else None)


def inspect_environment(python: str, *, uv: bool = False, process: PreparationProcess | None = None) -> EnvironmentSnapshot:
    # Raw metadata diagnostics may inspect an interrupted installation, but
    # never run concurrently with a package writer. Preparation is stricter.
    probe = "manager = __import__('sys').argv[1]\n" + _PROBE + "\nprint(json.dumps(snapshot))\n"
    arguments = ["-c", probe, "uv" if uv else "pip"]
    result = (process.run(python, arguments, timeout=15) if process is not None else
              inspect_python_environment(python, str(Path(python).parent.parent.resolve()), probe,
                                         arguments=("uv" if uv else "pip",), allow_incomplete=True))
    if result.returncode:
        raise ValueError("Could not verify the selected package environment; use its installation owner")
    return EnvironmentSnapshot.parse(json.loads(result.stdout))


def current_environment(*, uv: bool = False) -> EnvironmentSnapshot:
    """Inspect in an already initialized, lease-owning target child, without a grandchild."""
    scope: dict[str, object] = {"manager": "uv" if uv else "pip"}
    exec(compile(_PROBE, "<update environment probe>", "exec"), scope)
    return EnvironmentSnapshot.parse(scope["snapshot"])


@dataclass(frozen=True)
class StagedWheel:
    filename: str
    name: str
    version: str
    size: int
    sha256: str

    @classmethod
    def parse(cls, value: object) -> StagedWheel:
        data = _object(value)
        filename, name = _text(data["filename"]), _text(data["name"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.whl", filename) or not re.fullmatch(r"[a-z0-9-]+", name):
            raise ValueError("Invalid staged wheel name")
        if name == "pip":
            raise ValueError("An application update cannot replace its installer")
        return cls(filename, name, _text(data["version"]), _integer(data["size"]), _sha(data["sha256"]))

    def verify(self, directory: Path) -> Path:
        path = directory / self.filename
        if path.is_symlink() or path.stat().st_size != self.size:
            raise ValueError("Staged wheel size or file type changed")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != self.sha256:
                raise ValueError("Staged wheel checksum changed")
        with ZipFile(path) as wheel:
            names = wheel.namelist()
            if len(names) != len(set(names)) or any(re.search(r"(^[A-Za-z]:|^/|\\|(?:^|/)\.\.(?:/|$))", name) for name in names):
                raise ValueError("Invalid wheel paths")
            metadata = [item for item in wheel.infolist() if item.filename.endswith(".dist-info/METADATA")]
            if len(metadata) != 1 or metadata[0].file_size > 256 * 1024:
                raise ValueError("Invalid wheel metadata")
            parsed = BytesParser().parsebytes(wheel.read(metadata[0]))
            name = re.sub(r"[-_.]+", "-", str(parsed["Name"])).lower()
            if (name, parsed["Version"]) != (self.name, self.version):
                raise ValueError("Staged wheel identity changed")
        return path


@dataclass(frozen=True)
class WorkerSpec:
    plan_id: str
    plan_sha256: str
    worker_sha256: str
    baseline: EnvironmentSnapshot
    version: str
    wheels: tuple[StagedWheel, ...]
    backup_sources: tuple[BackupSource, ...]
    restart_profiles: tuple[str, ...] = ()
    uv: UVPreparation | None = None
    automatic_recovery: bool = False

    @staticmethod
    def recovery_selected(directory: Path) -> bool:
        """Read the frozen selection for status, without probing damaged inputs."""
        try:
            data = read_record(directory / "request.json", max_bytes=_MAX_REQUEST_BYTES)
        except FileNotFoundError:
            return False  # Preparation has not committed a worker request.
        if data.get("plan_id") != directory.name:
            raise ValueError("Update job identity mismatch")
        return data.get("automatic_recovery") is True

    @classmethod
    def read(cls, directory: Path) -> WorkerSpec:
        data = read_record(directory / "request.json", max_bytes=_MAX_REQUEST_BYTES)
        if data.get("schema_version") != _REQUEST_SCHEMA_VERSION:
            raise ValueError("Unsupported update worker request")
        plan_id = _text(data["plan_id"])
        if str(UUID(plan_id)) != plan_id or directory.name != plan_id:
            raise ValueError("Update job identity mismatch")
        raw_wheels = data["wheels"]
        if not isinstance(raw_wheels, list):
            raise ValueError("Invalid update wheel set")
        wheel_values = cast(list[object], raw_wheels)
        if not 1 <= len(wheel_values) <= 500:
            raise ValueError("Invalid update wheel set")
        wheels = tuple(StagedWheel.parse(value) for value in wheel_values)
        raw_sources = data.get("backup_sources")
        if not isinstance(raw_sources, list):
            raise ValueError("Invalid backup scope")
        source_values = cast(list[object], raw_sources)
        if not 1 <= len(source_values) <= 40_000:
            raise ValueError("Invalid backup scope")
        sources = tuple(BackupSource.parse(value) for value in source_values)
        participants = data.get("restart_profiles")
        if not isinstance(participants, list):
            raise ValueError("Invalid restart participants")
        restart_profiles = tuple(_sha(value) for value in cast(list[object], participants))
        if len(restart_profiles) > 1024 or len(set(restart_profiles)) != len(restart_profiles):
            raise ValueError("Invalid restart participants")
        automatic_recovery = data.get("automatic_recovery", False)
        if type(automatic_recovery) is not bool:
            raise ValueError("Invalid automatic recovery selection")
        spec = cls(plan_id, _sha(data["plan_sha256"]), _sha(data["worker_sha256"]), EnvironmentSnapshot.parse(data["baseline"]),
                   _text(data["version"]), wheels, sources, restart_profiles,
                   UVPreparation.parse(data["uv"]) if data.get("uv") is not None else None,
                   automatic_recovery)
        if (spec.uv is None) != (spec.baseline.manager_receipt_sha is None):
            raise ValueError("Installer preparation does not match the environment owner")
        if spec.uv is not None and (spec.uv.receipt_sha256 != spec.baseline.manager_receipt_sha
                                    or spec.uv.versions.get("nanobot-ai") != spec.version):
            raise ValueError("The uv preparation does not match the approved installation or target")
        if directory.resolve() != (installation_state_dir(spec.baseline.environment) / "jobs" / plan_id).resolve():
            raise ValueError("Update job is outside its installation state directory")
        if len({wheel.name for wheel in wheels}) != len(wheels):
            raise ValueError("Duplicate staged distributions")
        if [(wheel.name, wheel.version) for wheel in wheels if wheel.name == "nanobot-ai"] != [("nanobot-ai", spec.version)]:
            raise ValueError("Missing exact nanobot target")
        if hashlib.sha256((directory / "plan.json").read_bytes()).hexdigest() != spec.plan_sha256:
            raise ValueError("The approved plan changed")
        if hashlib.sha256((directory / "worker.pyz").read_bytes()).hexdigest() != spec.worker_sha256:
            raise ValueError("The staged update worker changed")
        return spec

    def save(self, directory: Path) -> None:
        # Expanded profile stores may exceed the small journal/approval limit.
        # Keep the writer and standalone reader on the same bounded contract.
        write_record(directory / "request.json", {"schema_version": _REQUEST_SCHEMA_VERSION, **asdict(self)},
                     max_bytes=_MAX_REQUEST_BYTES)

    def verify_inputs(self, directory: Path) -> None:
        for wheel in self.wheels:
            path = wheel.verify(directory / "wheels")
            if self.restart_profiles and wheel.name == "nanobot-ai":
                with ZipFile(path) as archive:
                    verify_target_handoff(archive)
        if self.uv is not None:
            self.uv.verify(self.baseline.environment, directory)

    @contextmanager
    def mutation_access(self) -> Generator[tuple[FileLease, DataLease]]:
        """Hold this job's installation and data leases, in acquisition order."""
        with (installation_access(updating=True, environment=self.baseline.environment) as installation,
              data_access((source.path for source in self.backup_sources), updating=True, job_id=self.plan_id) as data):
            yield installation, data


class Phase(str, Enum):
    PREPARATION_REQUESTED = "preparation_requested"
    PREPARING = "preparing"
    PREPARATION_FAILED = "preparation_failed"
    READY = "ready"
    CHECKING = "checking"
    STOPPING = "stopping"
    HANDOFF_FAILED = "handoff_failed"
    BACKING_UP = "backing_up"
    INSTALLING = "installing"
    VERIFYING = "verifying"
    INSTALLED = "installed"
    RESTARTING = "restarting"
    ACTIVATING = "activating"
    FINALIZING = "finalizing"
    RESTART_FAILED = "restart_failed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RESTORED = "restored"


@dataclass(frozen=True)
class JobStatus:
    plan_id: str
    phase: Phase
    attempt: int
    mutation_started: bool
    message: str
    updated_at: int

    @classmethod
    def read(cls, directory: Path) -> JobStatus:
        value = read_record(directory / "status.json")
        mutated = value["mutation_started"]
        if type(mutated) is not bool or value["plan_id"] != directory.name:
            raise ValueError("Invalid update status")
        return cls(directory.name, Phase(value["phase"]), _integer(value["attempt"]), mutated,
                   _text(value["message"]), _integer(value["updated_at"]))

    def save(self, directory: Path) -> None:
        write_record(directory / "status.json", asdict(self))

    def advance(self, directory: Path, phase: Phase, message: str, *,
                mutation_started: bool | None = None, attempt: int | None = None) -> JobStatus:
        """Publish a phase without reconstructing the job's execution history."""
        status = JobStatus(self.plan_id, phase, self.attempt if attempt is None else attempt,
                           self.mutation_started if mutation_started is None else mutation_started,
                           message, int(time.time()))
        status.save(directory)
        return status


@dataclass(frozen=True)
class ExecutionConfirmation:
    """One durable user confirmation; not proof that a worker is currently alive."""

    id: str
    plan_id: str
    request_sha256: str
    created_at: int
    expires_at: int

    @classmethod
    def read(cls, directory: Path) -> ExecutionConfirmation | None:
        try:
            value = read_record(directory / "confirmation.json", max_bytes=2048)
        except FileNotFoundError:
            return None
        identifier, plan_id = _text(value["id"]), _text(value["plan_id"])
        if UUID(identifier).hex != identifier or str(UUID(plan_id)) != plan_id or plan_id != directory.name:
            raise ValueError("Invalid execution confirmation identity")
        created, expires = _integer(value["created_at"]), _integer(value["expires_at"])
        if not created < expires <= created + 900:
            raise ValueError("Invalid execution confirmation lifetime")
        return cls(identifier, plan_id, _sha(value["request_sha256"]), created, expires)

    def save(self, directory: Path) -> None:
        write_record(directory / "confirmation.json", asdict(self), max_bytes=2048)


def check_approval(directory: Path, spec: WorkerSpec, *, handoff: bool = False,
                    confirmation_id: str | None = None, check_expiry: bool = True) -> dict[str, object]:
    approval = read_record(directory / ("handoff-approval.json" if handoff else "approval.json"))
    now = int(time.time())
    created, expires = _integer(approval["created_at"]), _integer(approval["expires_at"])
    if not created < expires <= created + 900 or (check_expiry and not created <= now < expires):
        raise ValueError("Update approval expired; review this exact job again before retrying")
    digest = hashlib.sha256((directory / "request.json").read_bytes()).hexdigest()
    if approval.get("request_sha256") != digest or approval.get("plan_id") != spec.plan_id:
        raise ValueError("Update approval does not match this job")
    if confirmation_id is not None:
        confirmation = ExecutionConfirmation.read(directory)
        if (confirmation is None or confirmation.id != confirmation_id
                or approval.get("confirmation_id") != confirmation_id
                or confirmation.request_sha256 != digest or confirmation.plan_id != spec.plan_id
                or (confirmation.created_at, confirmation.expires_at) != (created, expires)):
            raise ValueError("Execution confirmation was replaced or revoked")
    return approval


def _prepare_handoff_child(directory: Path, confirmation_id: str | None = None) -> None:
    spec = WorkerSpec.read(directory)
    # The child imports the old application, but keeps a shared lease until it
    # actually exits. Parent loss cannot allow another installer to replace its
    # imports. The base-Python parent waits for this exit before changing files.
    child_leases.enter_context(file_access(
        installation_state_dir(spec.baseline.environment) / "handoff-child.lock", exclusive=True))
    child_leases.enter_context(installation_access(environment=spec.baseline.environment))
    check_approval(directory, spec, handoff=True, confirmation_id=confirmation_id)
    initialize_runtime(spec.baseline.python, spec.baseline.environment)
    from nanobot.update_handoff import prepare_handoff

    prepare_handoff(directory)


def _handoff(directory: Path, spec: WorkerSpec, confirmation_id: str | None = None) -> None:
    status = JobStatus.read(directory)
    check_approval(directory, spec, handoff=True, confirmation_id=confirmation_id)
    status.advance(directory, Phase.CHECKING, "Rechecking the exact release and installation before shutdown", mutation_started=False)
    subprocess.run([spec.baseline.python, "-I", "-S", str(directory / "worker.pyz"),
                    "--prepare-handoff", str(directory), *([confirmation_id] if confirmation_id else [])], check=True, timeout=300,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    approval = check_approval(directory, spec, handoff=True, confirmation_id=confirmation_id)
    current = inspect_job_environment(directory, spec)
    with spec.mutation_access():
        check_environment(spec, repairing=False, current=current)
        spec.verify_inputs(directory)
        # Stopping a process did not grant installation authority. Only successful
        # preflight, child exit and exclusive installation/data leases get here.
        write_record(directory / "approval.json", approval)


def check_environment(spec: WorkerSpec, *, repairing: bool, current: EnvironmentSnapshot) -> None:
    if current.installer_receipt_sha != spec.baseline.installer_receipt_sha:
        raise ValueError("Installer selection changed outside this update")
    if (current.environment, current.python, current.base_python, current.receipt_sha, current.manager_receipt_sha) != (
        spec.baseline.environment, spec.baseline.python, spec.baseline.base_python, spec.baseline.receipt_sha,
        spec.baseline.manager_receipt_sha,
    ):
        raise ValueError("Installation ownership or interpreter changed")
    changed: set[str] = {wheel.name for wheel in spec.wheels} if repairing else set()
    targets = {wheel.name: wheel.version for wheel in spec.wheels}
    if spec.uv is not None:
        targets = spec.uv.versions
        if repairing:
            changed = set(spec.baseline.versions) | set(targets)
    before = {name: digest for name, digest in spec.baseline.distributions.items() if name not in changed}
    after = {name: digest for name, digest in current.distributions.items() if name not in changed}
    if before != after:
        raise ValueError("The package environment changed outside this update; review it before continuing")
    if repairing:
        for name in changed:
            if current.versions.get(name) not in {None, spec.baseline.versions.get(name), targets.get(name)}:
                raise ValueError("Another update changed a target package; repair cannot overwrite its version")


def require_pending_owner(spec: WorkerSpec) -> None:
    pending = pending_update_path(spec.baseline.environment)
    if pending.exists() and read_record(pending).get("job_id") != spec.plan_id:
        raise ValueError("Another incomplete update owns this installation")


def inspect_job_environment(directory: Path, spec: WorkerSpec) -> EnvironmentSnapshot:
    """Inspect a staged job without borrowing its caller's runtime/data leases.

    Call with the worker lease held, but not exclusive runtime/data leases. The
    child owns those while loading site and retains them through exit cleanup.
    The caller still checks the snapshot under its final admission leases, and
    the installer repeats that check in-process immediately before mutation.
    """
    result = subprocess.run([spec.baseline.python, "-I", "-S", str(directory / "worker.pyz"),
                             "--inspect", str(directory)], capture_output=True, text=True, timeout=15)
    if result.returncode == 11:
        raise InstallationBusyError("The update's installation or data is in use; wait for its current owner")
    if result.returncode:
        raise ValueError("Could not verify the selected package environment; use its installation owner")
    return EnvironmentSnapshot.parse(json.loads(result.stdout))


def _inspection_child(directory: Path) -> None:
    spec = WorkerSpec.read(directory)
    status = JobStatus.read(directory)
    restarting = status.phase in {Phase.RESTARTING, Phase.ACTIVATING, Phase.FINALIZING, Phase.RESTART_FAILED}
    child_leases.enter_context(installation_access(
        updating=not restarting, allow_incomplete=restarting, environment=spec.baseline.environment))
    # Finalization can already have released the data reservation while the
    # verified gateway is serving requests. It only needs the runtime read lease.
    if status.phase != Phase.FINALIZING:
        child_leases.enter_context(data_access(
            (source.path for source in spec.backup_sources), updating=not restarting, job_id=spec.plan_id))
    require_pending_owner(spec)
    initialize_runtime(spec.baseline.python, spec.baseline.environment)
    print(json.dumps(asdict(current_environment(uv=spec.uv is not None))))


def _installer_child(directory: Path, confirmation_id: str | None = None) -> None:
    spec = WorkerSpec.read(directory)
    installation, data = child_leases.enter_context(spec.mutation_access())
    status = JobStatus.read(directory)
    if status.phase in {Phase.INSTALLED, Phase.CANCELLED, Phase.RESTARTING,
                        Phase.ACTIVATING, Phase.FINALIZING, Phase.RESTART_FAILED, Phase.SUCCEEDED, Phase.RESTORED}:
        raise ValueError("This update job is already finished")
    check_approval(directory, spec, confirmation_id=confirmation_id)
    require_pending_owner(spec)
    initialize_runtime(spec.baseline.python, spec.baseline.environment)
    check_environment(spec, repairing=status.mutation_started, current=current_environment(uv=spec.uv is not None))
    spec.verify_inputs(directory)
    wheels = [str(directory / "wheels" / wheel.filename) for wheel in spec.wheels]
    uv_cache = None
    if spec.uv is not None:
        if os.name != "posix":
            raise ValueError("Native uv lease handoff is not available on this platform")
        uv_cache = spec.uv.working_cache(directory)
    verify_backup(directory, spec.backup_sources, hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
                  unchanged=not status.mutation_started)
    pending = pending_update_path()
    pending.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.reserve()
    write_record(pending, {"schema_version": 2, "job_id": spec.plan_id, "version": spec.version})
    status.advance(directory, Phase.INSTALLING, "Installing the verified package files",
                   mutation_started=True, attempt=status.attempt + 1)
    if spec.uv is not None and uv_cache is not None:
        # Exact-wheel override is one operation, not a rewrite of the saved
        # requirement. Even --no-build would persist in the user's receipt.
        plan = read_record(directory / "plan.json", max_bytes=_MAX_REQUEST_BYTES)
        extras = plan.get("extras")
        if not isinstance(extras, list):
            raise ValueError("Invalid approved uv extras")
        extra_values = cast(list[object], extras)
        if not all(isinstance(extra, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", extra)
                   for extra in extra_values):
            raise ValueError("Invalid approved uv extras")
        suffix = "[" + ",".join(cast(list[str], extra_values)) + "]" if extras else ""
        app = next(wheel for wheel in spec.wheels if wheel.name == "nanobot-ai")
        target = "nanobot-ai" + suffix + " @ " + (directory / "wheels" / app.filename).as_uri()
        env = uv_environment(tools=Path(spec.baseline.environment).parent,
                             binaries=Path(spec.uv.binaries), cache=uv_cache)
        arguments = [spec.uv.executable, "tool", "upgrade", "--no-config", "--offline", "--reinstall", target]
        with installation.inherit_for_exec(), data.inherit_for_exec():
            os.execve(spec.uv.executable, arguments, env)
    # Keep pip in this lease-owning process on every platform. Inherited Windows
    # handles cannot transfer byte-range locks; a POSIX wrapper can also die
    # before a spawned installer. Only verified local wheels are accepted, so
    # no build child can outlive it. A separate protected child verifies afterwards.
    arguments = ["--disable-pip-version-check", "--no-input", "install",
                 "--no-index", "--no-deps", "--only-binary=:all:", "--no-compile",
                 "--force-reinstall", *wheels]
    # A dedicated CLI, ending in pip's SystemExit; no application or second pip
    # call runs afterwards. Process-owned leases remain held during atexit.
    sys.argv = ["pip", *arguments]
    runpy.run_module("pip", run_name="__main__")


def _verify(spec: WorkerSpec, directory: Path) -> None:
    # The coordinator must not hold the runtime/data leases here: this child
    # acquires its own before site/imports and keeps them through dependency
    # checks and atexit, even if the coordinator disappears.
    verification_id = uuid4().hex
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}
    env["PIP_CONFIG_FILE"] = os.devnull
    result = subprocess.run([spec.baseline.python, "-I", "-S", str(directory / "worker.pyz"),
                             "--verify", str(directory), verification_id], timeout=90,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    if result.returncode == 10:
        raise ValueError("The installed nanobot package does not import")
    if result.returncode:
        raise ValueError("Installed package or dependency verification failed")
    try:
        checkpoint = read_record(directory / "verification.json", max_bytes=2048)
    except (OSError, ValueError) as exc:
        raise ValueError("Installed package verification did not finish") from exc
    if checkpoint.get("id") != verification_id:
        raise ValueError("Installed package verification did not finish")


def _verification_child(directory: Path, verification_id: str) -> None:
    if UUID(verification_id).hex != verification_id:
        raise ValueError("Invalid verification identity")
    spec = WorkerSpec.read(directory)
    installation, data = child_leases.enter_context(spec.mutation_access())
    status = JobStatus.read(directory)
    if not status.mutation_started or status.phase not in {Phase.VERIFYING, Phase.INSTALLED}:
        raise ValueError("This job is not awaiting installed-package verification")
    if read_record(pending_update_path(spec.baseline.environment)).get("job_id") != spec.plan_id:
        raise ValueError("This job no longer owns installed-package verification")
    spec.verify_inputs(directory)
    initialize_runtime(spec.baseline.python, spec.baseline.environment)
    try:
        import nanobot
    except Exception:
        # A dedicated exit code preserves an actionable diagnosis without
        # persisting arbitrary import exceptions, paths or package output.
        raise SystemExit(10) from None
    package = Path(nanobot.__file__).resolve()
    if nanobot.__version__ != spec.version or not package.is_relative_to(spec.baseline.environment):
        raise ValueError("Installed package version or location differs from the approved target")
    app = next(wheel for wheel in spec.wheels if wheel.name == "nanobot-ai")
    with ZipFile(directory / "wheels" / app.filename) as wheel:
        for item in wheel.infolist():
            if item.is_dir() or not item.filename.startswith("nanobot/"):
                continue
            installed = package.parent.parent / item.filename
            if not installed.is_file() or installed.is_symlink():
                raise ValueError("An installed application file is missing")
            with installed.open("rb") as actual, wheel.open(item) as expected:
                digest = hashlib.sha256()
                while chunk := expected.read(1024 * 1024):
                    digest.update(chunk)
                if hashlib.file_digest(actual, "sha256").digest() != digest.digest():
                    raise ValueError("Installed application files differ from the verified wheel")
    if spec.uv is not None:
        current = current_environment(uv=True)
        if (current.environment, current.python, current.base_python, current.receipt_sha) != (
            spec.baseline.environment, spec.baseline.python, spec.baseline.base_python, spec.baseline.receipt_sha,
        ):
            raise ValueError("uv changed the prepared interpreter or environment ownership")
        if current.versions != spec.uv.versions:
            raise ValueError("The installed uv dependencies differ from the prepared transaction")
        if os.name != "posix":
            raise ValueError("Native uv lease handoff is not available on this platform")
        command = [spec.uv.executable, "pip", "check", "--no-config", "--no-cache", "--offline", "--python", spec.baseline.python]
        env = uv_environment(tools=Path(spec.baseline.environment).parent,
                             binaries=Path(spec.uv.binaries), cache=directory / ".uv-check-cache")
        # This checkpoint plus the native command's successful exit proves the
        # verification path ran. Exit 0 from site/import hooks alone does not.
        write_record(directory / "verification.json", {"id": verification_id}, max_bytes=2048)
        with installation.inherit_for_exec(), data.inherit_for_exec():
            os.execve(spec.uv.executable, command, env)
    # Like installation, pip check runs in the same process that owns the
    # leases, not in an unprotected subprocess of a protected wrapper.
    sys.argv = ["pip", "check"]
    try:
        runpy.run_module("pip", run_name="__main__")
    except SystemExit as exc:
        if exc.code not in {None, 0}:
            raise
    write_record(directory / "verification.json", {"id": verification_id}, max_bytes=2048)


def _approve_recovery(directory: Path, spec: WorkerSpec, status: JobStatus) -> None:
    """Fresh local consent resumes only a previously admitted, immutable job.

    Never repeats shutdown or resolves a release. Before mutation, the original
    handoff must already have admitted this worker (approval.json). After mutation
    the same installation/data reservation and backup remain authoritative.
    """
    if status.phase in {Phase.CANCELLED, Phase.PREPARATION_FAILED, Phase.PREPARING, Phase.PREPARATION_REQUESTED}:
        raise ValueError("This job cannot be repaired; no installation was admitted")
    check_approval(directory, spec, check_expiry=False)
    spec.verify_inputs(directory)
    current = inspect_job_environment(directory, spec)
    check_environment(spec, repairing=status.mutation_started, current=current)
    if status.mutation_started:
        verify_backup(directory, spec.backup_sources,
                      hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(), unchanged=False)
    now = int(time.time())
    write_record(directory / "approval.json", {
        "plan_id": spec.plan_id,
        "request_sha256": hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
        "created_at": now, "expires_at": now + 900,
    })


def run_job(directory: Path, *, handoff: bool = False, confirmation_id: str | None = None,
            recover: bool = False) -> JobStatus:
    """Execute one approved offline job. 'installed' does not mean restarted."""
    spec = WorkerSpec.read(directory)
    root = installation_state_dir(spec.baseline.environment)
    with file_access(root / "worker.lock", exclusive=True):
        if recover and (handoff or confirmation_id is not None):
            raise ValueError("Repair cannot initiate a second shutdown handoff")
        if confirmation_id is not None:
            if not handoff:
                raise ValueError("A confirmation only starts the reviewed shutdown handoff")
            confirmation = ExecutionConfirmation.read(directory)
            if confirmation is None or confirmation.id != confirmation_id:
                raise ValueError("This execution confirmation is no longer current")
            claimed = directory / "confirmation-claimed.json"
            if claimed.exists():
                if read_record(claimed, max_bytes=2048).get("id") != confirmation_id:
                    raise ValueError("Another execution confirmation owns this job")
                # A duplicate or delayed launcher is history, not a retry, even
                # if the first worker exited before updating its journal.
                return JobStatus.read(directory)
            check_approval(directory, spec, handoff=True, confirmation_id=confirmation_id)
            write_record(claimed, {"id": confirmation_id}, max_bytes=2048)
        if handoff:
            # An orphan preflight child may still own the old runtime. Refuse a
            # competing handoff without rewriting its durable progress.
            with file_access(root / "handoff-child.lock", exclusive=True):
                pass
        status = JobStatus.read(directory)
        if status.phase == Phase.RESTORED:
            raise ValueError("This update was settled by service recovery; review a new update instead")
        if status.phase == Phase.CANCELLED:
            raise ValueError("This update job was cancelled")
        if recover:
            with file_access(root / "handoff-child.lock", exclusive=True):
                if status.phase == Phase.SUCCEEDED:
                    return status
                _approve_recovery(directory, spec, status)
        if handoff and (status.mutation_started or status.phase not in {
            Phase.READY, Phase.CHECKING, Phase.STOPPING, Phase.HANDOFF_FAILED,
        }):
            raise ValueError("Shutdown handoff requires an unmodified prepared job")
        try:
            if handoff:
                spec.verify_inputs(directory)
                _handoff(directory, spec, confirmation_id)
            if status.phase in {Phase.RESTARTING, Phase.ACTIVATING, Phase.FINALIZING, Phase.RESTART_FAILED, Phase.SUCCEEDED}:
                return restart_runtime(directory, spec, confirmation_id)
            if status.phase == Phase.INSTALLED:
                # Recover a crash after saving the result but before removing
                # the startup fence. Verification owns independent leases.
                with spec.mutation_access():
                    require_pending_owner(spec)
                    needs_verification = pending_update_path(spec.baseline.environment).exists()
                if needs_verification:
                    _verify(spec, directory)
                with spec.mutation_access() as (_, data):
                    require_pending_owner(spec)
                    pending_update_path(spec.baseline.environment).unlink(missing_ok=True)
                    data.release_reservation()
                return status
            check_approval(directory, spec, confirmation_id=confirmation_id)
            current = inspect_job_environment(directory, spec)
            with spec.mutation_access() as (_, data):
                require_pending_owner(spec)
                check_approval(directory, spec, confirmation_id=confirmation_id)
                check_environment(spec, repairing=status.mutation_started, current=current)
                spec.verify_inputs(directory)
                if not status.mutation_started:
                    from nanobot.update_fallback import preserve_program

                    preserve_program(directory, spec)
                status.advance(directory, Phase.BACKING_UP, "Preserving the original scoped data backup")
                ensure_backup(directory, spec.backup_sources,
                              hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
                              mutated=status.mutation_started)
                # Block shared-data writers too, including a different Python
                # installation, across handoff and interrupted-job recovery.
                data.reserve()
                pending = pending_update_path(spec.baseline.environment)
                pending.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                write_record(pending, {"schema_version": 2, "job_id": spec.plan_id, "version": spec.version})
            env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}
            env["PIP_CONFIG_FILE"] = os.devnull
            subprocess.run([spec.baseline.python, "-I", "-S", str(directory / "worker.pyz"),
                            "--install", str(directory), *([confirmation_id] if confirmation_id else [])], check=True, timeout=900,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            with spec.mutation_access():
                status = JobStatus.read(directory)
                status.advance(directory, Phase.VERIFYING, "Checking the installed package and dependencies", mutation_started=True)
            _verify(spec, directory)
            with spec.mutation_access() as (_, data):
                require_pending_owner(spec)
                status = status.advance(directory, Phase.RESTARTING if spec.restart_profiles else Phase.INSTALLED,
                                        "Files installed and checked; running gateway not yet verified", mutation_started=True)
                if not spec.restart_profiles:
                    pending_update_path(spec.baseline.environment).unlink()
                    data.release_reservation()
                    return status
            return restart_runtime(directory, spec, confirmation_id)
        except InstallationBusyError:
            # An orphan pip child may still be alive. Do not turn its ongoing
            # installation into a terminal failure or overwrite its journal.
            current = JobStatus.read(directory)
            if handoff and current.phase in {Phase.CHECKING, Phase.STOPPING} and not current.mutation_started:
                current.advance(directory, Phase.HANDOFF_FAILED,
                                "Update handoff could not acquire exclusive access; no package files were changed", mutation_started=False)
            raise
        except Exception as exc:
            status = JobStatus.read(directory)
            if status.phase in {Phase.FINALIZING, Phase.SUCCEEDED}:
                # Runtime success was durably verified. Retry only final cleanup,
                # never demote it to a restart or package-repair transaction.
                raise
            # Do not persist arbitrary package-manager output, URLs or credentials.
            message = str(exc) if isinstance(exc, (ValueError, InstallationBusyError)) else f"Update failed ({type(exc).__name__})"
            handoff_failed = status.phase in {Phase.CHECKING, Phase.STOPPING, Phase.HANDOFF_FAILED}
            if handoff_failed:
                # The old runtime may already have exited. Never imply that a
                # pre-install failure undoes a durable shutdown commitment.
                message = (status.message if status.phase == Phase.HANDOFF_FAILED else
                           "Update handoff did not finish; review the saved shutdown state before retrying")
            phase = Phase.HANDOFF_FAILED if handoff_failed else (
                Phase.RESTART_FAILED if status.phase in {
                    Phase.RESTARTING, Phase.ACTIVATING, Phase.RESTART_FAILED,
                } else Phase.FAILED
            )
            status.advance(directory, phase, message[:1000])
            if not status.mutation_started and not handoff_failed:
                with spec.mutation_access() as (_, data):
                    require_pending_owner(spec)
                    pending_update_path(spec.baseline.environment).unlink(missing_ok=True)
                    data.release_reservation()
            raise


def restart_runtime(directory: Path, spec: WorkerSpec, confirmation_id: str | None = None) -> JobStatus:
    # Use the target Python, but enter through frozen stdlib code so its shared
    # installation lease is held before importing the mutable target runtime.
    subprocess.run([spec.baseline.python, "-I", "-S", str(directory / "worker.pyz"),
                    "--restart", str(directory), *([confirmation_id] if confirmation_id else [])], check=True, timeout=300,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = JobStatus.read(directory)
    if result.phase not in {Phase.SUCCEEDED, Phase.RESTORED}:
        raise ValueError("Runtime handoff did not verify the updated gateways")
    return result


def _runtime_child(directory: Path, participant: str | None = None, confirmation_id: str | None = None) -> None:
    spec = WorkerSpec.read(directory)
    if not spec.restart_profiles or (participant is not None and participant not in spec.restart_profiles):
        raise ValueError("This gateway is not a reviewed restart participant")
    child_leases.enter_context(installation_access(allow_incomplete=True, environment=spec.baseline.environment))
    require_pending_owner(spec)
    if confirmation_id is not None:
        # Completion can take longer than consent's launch window. Bind the
        # identity, without treating elapsed time as a reason to reinstall.
        check_approval(directory, spec, confirmation_id=confirmation_id, check_expiry=False)
    initialize_runtime(spec.baseline.python, spec.baseline.environment)
    # Deliberately import the installed application, not a frozen stub.
    if (directory / "restoration.json").exists():
        # Recovery uses the original frozen restart implementation. An older
        # installed package need not understand the newer recovery journal.
        from .update_restart import run_gateway, run_restarts
    else:
        import importlib

        restart = importlib.import_module("nanobot.update_restart")
        run_gateway, run_restarts = restart.run_gateway, restart.run_restarts

    if participant is None:
        run_restarts(directory)
    else:
        run_gateway(directory, participant)


def cancel_job(directory: Path) -> JobStatus:
    """Cancel only a stopped, unmodified job; never terminate an installer."""
    spec = WorkerSpec.read(directory)
    with file_access(installation_state_dir(spec.baseline.environment) / "worker.lock", exclusive=True):
        with spec.mutation_access() as (_, data):
            status = JobStatus.read(directory)
            if status.mutation_started:
                raise ValueError("Installation has begun; this job needs verification or repair, not cancellation")
            require_pending_owner(spec)
            pending_update_path(spec.baseline.environment).unlink(missing_ok=True)
            data.release_reservation()
            status = status.advance(directory, Phase.CANCELLED, "Cancelled; installed files were not changed", mutation_started=False)
            (directory / "approval.json").unlink(missing_ok=True)
            return status


def main() -> None:
    if len(sys.argv) >= 4 and sys.argv[1] == "--supervise":
        from nanobot.update_fallback import supervise

        supervise(Path(sys.argv[2]).resolve(), sys.argv[3:])
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--inspect":
        try:
            _inspection_child(Path(sys.argv[2]).resolve())
        except InstallationBusyError:
            raise SystemExit(11) from None
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--prepare-native":
        run_preparation_child(Path(sys.argv[2]).resolve())
        return
    if len(sys.argv) in {3, 4} and sys.argv[1] == "--prepare-handoff":
        _prepare_handoff_child(Path(sys.argv[2]).resolve(), sys.argv[3] if len(sys.argv) == 4 else None)
        return
    if len(sys.argv) in {3, 4} and sys.argv[1] == "--restart":
        _runtime_child(Path(sys.argv[2]).resolve(), confirmation_id=sys.argv[3] if len(sys.argv) == 4 else None)
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--gateway":
        _runtime_child(Path(sys.argv[2]).resolve(), sys.argv[3])
        return
    if len(sys.argv) in {3, 4} and sys.argv[1] == "--install":
        _installer_child(Path(sys.argv[2]).resolve(), sys.argv[3] if len(sys.argv) == 4 else None)
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--verify":
        _verification_child(Path(sys.argv[2]).resolve(), sys.argv[3])
        return
    if len(sys.argv) == 3 and sys.argv[1] in {"--status", "--cancel"}:
        directory = Path(sys.argv[2]).resolve()
        WorkerSpec.read(directory)
        status = cancel_job(directory) if sys.argv[1] == "--cancel" else JobStatus.read(directory)
        print(json.dumps(asdict(status)))
        return
    recover = len(sys.argv) == 3 and sys.argv[1] == "--recover"
    handoff = len(sys.argv) == 3 and sys.argv[1] == "--handoff"
    confirmed = len(sys.argv) == 4 and sys.argv[1] == "--confirmed-handoff"
    if len(sys.argv) != 2 and not handoff and not confirmed and not recover:
        raise SystemExit("Use this worker with its exact saved job directory")
    directory = Path(sys.argv[2] if handoff or confirmed or recover else sys.argv[1]).resolve()
    try:
        result = run_job(directory, handoff=handoff or confirmed, confirmation_id=sys.argv[3] if confirmed else None,
                         recover=recover)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Update did not finish: {type(exc).__name__}. Consult the saved job status.", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(asdict(result)))


if __name__ == "__main__":
    main()
