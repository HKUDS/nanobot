"""Prepare exact offline jobs and hand them to the standalone installer worker.

The gateway controller keeps authenticated staging separate from execution consent.
The caller owns explicit shutdown/restart selection. A detached worker revalidates,
stops reviewed idle gateways, backs up data, installs, and restarts selected runtimes.
Confirmed execution is idempotent; managed installs have bounded detached recovery.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4
from zipfile import ZipFile, ZipInfo

from packaging.utils import canonicalize_name, parse_wheel_filename
from pydantic import BaseModel, ConfigDict, Field

from nanobot.data_access import data_access
from nanobot.installation_lock import (
    file_access,
    installation_access,
    installation_id,
    installation_state_dir,
)
from nanobot.installation_receipt import RECEIPT_NAME
from nanobot.release_feed import ReleaseFeed
from nanobot.releases import Channel, ReleaseRecord, Sha256
from nanobot.update_backup import BackupSource, unique_sources
from nanobot.update_plan import UpdatePlan
from nanobot.update_process import PreparationProcess
from nanobot.update_profiles import require_stopped_profiles, validate_profiles
from nanobot.update_uv import UVPreparation, prepare_uv
from nanobot.update_worker import (
    ExecutionConfirmation,
    JobStatus,
    Phase,
    StagedWheel,
    WorkerSpec,
    check_environment,
    inspect_environment,
    inspect_job_environment,
    read_record,
    verify_target_handoff,
    write_record,
)
from nanobot.utils.atomic_file import atomic_write_lines
from nanobot.utils.cancellation import shield_and_drain


class UpdateJobNotFoundError(FileNotFoundError):
    """No saved preparation or execution status exists for this installation."""


class UpdateJobView(ReleaseRecord):
    """Last durable facts only: not proof of a live worker or authority to retry."""

    id: str
    installation_id: str
    host: str
    previous_version: str
    target_version: str
    channel: Channel
    recorded_phase: Phase
    attempt: int
    mutation_started: bool
    updated_at: int
    execution_confirmation_id: str | None = None
    running_version: str = ""
    recovery_command: str = ""
    recovery_active: bool = False
    service_restored: bool = False
    automatic_recovery: bool = False


def _recovery_command(plan_id: str) -> str:
    # The installer accepts py or an explicit Python path. Neither guarantees
    # python/python3 is on PATH after failure. Use the base interpreter outside
    # the mutable venv, quoted for the operator's platform shell.
    python: object = getattr(sys, "_base_executable")
    if not isinstance(python, str):
        raise ValueError("Recovery needs a known base Python")
    # The operator's shell may have a different HOME from the gateway.
    launcher = str(installation_state_dir().parent / "recover.py")
    if platform.system() == "Windows":
        quoted = "'" + python.replace("'", "''") + "'"
        quoted_launcher = "'" + launcher.replace("'", "''") + "'"
        return f'& {quoted} -I -S {quoted_launcher} {plan_id} --repair'
    return f'{shlex.quote(python)} -I -S {shlex.quote(launcher)} {plan_id} --repair'


def read_update_job(plan_id: str) -> UpdateJobView:
    """Read the journal scoped to this environment path, without probing Python.

    No interpreter probe, network request or runtime lease is required. A failed
    installation and an active writer must not hide its last recorded state.
    This does not validate continued release eligibility, worker liveness or
    that an environment reinstalled at this path is still the reviewed one.
    """
    UpdatePlan.canonical_id(plan_id)
    directory = installation_state_dir() / "jobs" / plan_id
    if directory.is_symlink():
        raise ValueError("Invalid update job directory")
    try:
        plan = UpdatePlan.model_validate(read_record(directory / "plan.json"))
        status = JobStatus.read(directory)
    except FileNotFoundError as exc:
        raise UpdateJobNotFoundError("No saved update job is available") from exc
    if plan.id != plan_id or plan.installation.installation_id != installation_id():
        raise ValueError("Update job belongs to a different installation or plan")
    confirmation = ExecutionConfirmation.read(directory)
    # Local diagnostic messages may contain paths or exception details. Clients
    # receive typed facts and can localize phases, never raw journal messages.
    from nanobot import __version__

    recovery_active = False
    supervision = directory / "supervision.json"
    recovery_failed = False
    if supervision.exists():
        record = read_record(supervision)
        if record.get("plan_id") == plan_id:
            recovery_failed = (record.get("state") == "needs_attention"
                               and status.phase not in {Phase.SUCCEEDED, Phase.RESTORED, Phase.CANCELLED})
            try:
                with file_access(installation_state_dir() / "supervisor.lock", exclusive=True):
                    pass
            except BlockingIOError:
                recovery_active = True

    return UpdateJobView(
        id=plan_id, installation_id=plan.installation.installation_id, host=platform.node(),
        previous_version=plan.installation.installed_version, target_version=plan.target.version,
        # Older clients know FAILED and must not display a rolled-back update
        # as successful. New clients use the additive service result below.
        channel=plan.channel, recorded_phase=Phase.FAILED if status.phase == Phase.RESTORED or recovery_failed else status.phase,
        attempt=status.attempt,
        mutation_started=status.mutation_started, updated_at=status.updated_at,
        execution_confirmation_id=confirmation.id if confirmation else None,
        running_version=__version__,
        recovery_command=_recovery_command(plan_id),
        recovery_active=recovery_active,
        service_restored=status.phase == Phase.RESTORED,
        automatic_recovery=WorkerSpec.recovery_selected(directory),
    )


class _Metadata(BaseModel):
    name: str
    version: str


class _Hashes(BaseModel):
    sha256: Sha256


class _Archive(BaseModel):
    hashes: _Hashes


class _Download(BaseModel):
    url: str
    archive_info: _Archive


class _Install(BaseModel):
    metadata: _Metadata
    download_info: _Download


class _Report(BaseModel):
    model_config = ConfigDict(strict=True)
    version: str
    install: list[_Install] = Field(max_length=500)


def _pip(process: PreparationProcess, python: str, *arguments: str) -> None:
    result = process.run(python, ["-m", "pip", "--disable-pip-version-check", "--no-input", *arguments])
    if result.returncode:
        # Index URLs and resolver output may contain credentials. Do not put them
        # in the durable job or the WebUI response.
        raise ValueError("Could not prepare the pip transaction; check the installation's package-manager configuration")


def _worker_archive(path: Path) -> str:
    sources = Path(__file__).parent
    # The frozen worker must not shadow the newly installed application when
    # handing off to its runtime. Keep only the copied stdlib helpers in this
    # private namespace; intentional application imports retain `nanobot`.
    modules = ("update_worker", "update_uv", "update_process", "update_backup", "update_fallback",
               "update_restart", "data_access", "installation_lock", "utils.atomic_file")
    with ZipFile(path, "x") as bundle:
        files = {"__main__.py": b"from _nanobot_update.update_worker import main\nmain()\n",
                 "_nanobot_update/__init__.py": b"", "_nanobot_update/utils/__init__.py": b""}
        for module in modules:
            name = module.replace(".", "/") + ".py"
            source = (sources / name).read_text(encoding="utf-8")
            for dependency in modules:
                source = source.replace(f"from nanobot.{dependency} import", f"from _nanobot_update.{dependency} import")
            files[f"_nanobot_update/{name}"] = source.encode("utf-8")
        for name, data in files.items():
            bundle.writestr(ZipInfo(name), data)
    path.chmod(0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage_app(plan: UpdatePlan, app_wheel: Path, directory: Path) -> StagedWheel:
    wheels = directory / "wheels"
    wheels.mkdir(mode=0o700, exist_ok=True)
    artifact = plan.target.artifact
    app = StagedWheel(artifact.filename, "nanobot-ai", plan.target.version, artifact.size, artifact.sha256)
    destination = wheels / artifact.filename
    if not destination.exists():
        shutil.copyfile(app_wheel, destination)
    verified = app.verify(wheels)
    with ZipFile(verified) as archive:
        if plan.restart_profiles:
            verify_target_handoff(archive)
        metadata = BytesParser().parsebytes(archive.read(f"nanobot_ai-{app.version}.dist-info/METADATA"))
        available = {canonicalize_name(extra) for extra in metadata.get_all("Provides-Extra", [])}
        if not set(plan.extras or []).issubset(available):
            raise ValueError("The target release does not provide all confirmed extras")
    return app


def _prepare_wheels(plan: UpdatePlan, app_wheel: Path, directory: Path,
                    process: PreparationProcess) -> tuple[StagedWheel, ...]:
    app = _stage_app(plan, app_wheel, directory)
    wheels = directory / "wheels"
    records = [app]
    python = plan.installation.python
    _pip(process, python, "check")
    with tempfile.TemporaryDirectory(prefix=".resolve-", dir=directory) as temporary:
        root = Path(temporary)
        report_path = root / "report.json"
        extras = f"[{','.join(plan.extras)}]" if plan.extras else ""
        _pip(process, python, "install", "--dry-run", "--only-binary=:all:", "--upgrade",
             "--upgrade-strategy", "only-if-needed", "--report", str(report_path),
             f"nanobot-ai{extras} @ {app_wheel.as_uri()}")
        if report_path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Package-manager report exceeds its size limit")
        report = _Report.model_validate_json(report_path.read_bytes())
        if report.version != "1":
            raise ValueError("Unsupported pip report version")
        requirements: list[str] = []
        dependencies: list[tuple[str, str, str, str]] = []
        for item in report.install:
            name = canonicalize_name(item.metadata.name)
            if name == "nanobot-ai":
                if (item.metadata.version, item.download_info.archive_info.hashes.sha256) != (app.version, app.sha256):
                    raise ValueError("Resolver changed the approved nanobot target")
                continue
            url = item.download_info.url
            if any(character.isspace() for character in url) or urlsplit(url).scheme not in {"https", "file"}:
                raise ValueError("An update dependency must be an exact HTTPS or local wheel")
            filename = Path(unquote(urlsplit(url).path)).name
            wheel_name, version, _, _ = parse_wheel_filename(filename)
            if (wheel_name, str(version)) != (name, item.metadata.version) or name == "pip":
                raise ValueError("Resolver returned an unsupported dependency artifact")
            digest = item.download_info.archive_info.hashes.sha256
            requirements.append(f"{name} @ {url} --hash=sha256:{digest}")
            dependencies.append((filename, name, str(version), digest))
        if requirements:
            request = root / "requirements.txt"
            request.write_text("\n".join(requirements), encoding="utf-8")
            request.chmod(0o600)
            downloads = root / "downloads"
            _pip(process, python, "download", "--no-deps", "--only-binary=:all:", "--require-hashes",
                 "--dest", str(downloads), "--requirement", str(request))
            for filename, name, version, digest in dependencies:
                path = downloads / filename
                record = StagedWheel(filename, name, version, path.stat().st_size, digest)
                record.verify(downloads)
                shutil.copyfile(path, wheels / filename)
                records.append(record)
    return tuple(records)


def _prepare_transaction(plan: UpdatePlan, app_wheel: Path, directory: Path,
                         process: PreparationProcess) -> tuple[tuple[StagedWheel, ...], UVPreparation | None]:
    if plan.installation.owner != "uv":
        return _prepare_wheels(plan, app_wheel, directory, process), None
    executable = shutil.which("uv")
    if executable is None:
        raise ValueError("The installation's uv manager is not available")
    app = _stage_app(plan, app_wheel, directory)
    prepared = prepare_uv(environment=plan.installation.environment, python=plan.installation.python,
                          receipt_sha256=plan.installation.records["uv-receipt.toml"],
                          app_wheel=directory / "wheels" / app.filename, version=plan.target.version,
                          extras=plan.extras or [], directory=directory, executable=executable, process=process)
    return (app,), prepared


def validate_preparation(plan: UpdatePlan) -> None:
    """Check the supported preparation contract, without touching the environment."""
    if plan.installation.owner not in {"venv", "uv"} or plan.extras is None:
        raise ValueError("The worker requires a supported dedicated environment and explicitly confirmed extras")
    if plan.installation.owner == "uv" and (os.name != "posix" or plan.installation.manager is None):
        raise ValueError("This uv installation needs its owner's external update workflow")
    if plan.owner_restriction:
        raise ValueError(plan.owner_restriction)
    if plan.action != "upgrade":
        raise ValueError("This executor prepares upgrades only; no-op, restart and downgrade need their own review")
    plan.validate_for(plan.installation)


async def prepare_job(plan: UpdatePlan, feed: ReleaseFeed) -> Path:
    """Stage a supported job without granting execution or changing installed files."""
    validate_preparation(plan)
    native_uv = plan.installation.owner == "uv"
    root = installation_state_dir(plan.installation.environment)
    # A stable stdlib-only entrypoint survives missing application dependencies.
    # It selects the immutable per-job worker, not code in site-packages.
    recovery = root.parent / "recover.py"
    source = Path(__file__).with_name("update_recovery.py").read_text()
    if recovery.exists() and (recovery.is_symlink() or not recovery.read_text().startswith(
            '\"\"\"nanobot standalone recovery launcher, protocol 1.')):
        raise ValueError("The recovery launcher path is already owned by another file")
    atomic_write_lines(recovery, source.splitlines())
    recovery.chmod(0o600)
    with (file_access(root / "channel.lock", exclusive=False),
          installation_access(environment=plan.installation.environment), file_access(root / "prepare.lock", exclusive=True)):
        validate_preparation(plan)
        directory = root / "jobs" / plan.id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (directory / "request.json").exists():
            spec = WorkerSpec.read(directory)
            saved = (directory / "plan.json").read_bytes()
            if (UpdatePlan.model_validate_json(saved) != plan
                    or spec.plan_sha256 != hashlib.sha256(saved).hexdigest()):
                raise ValueError("This job already belongs to another approved plan")
            return directory
        if (directory / "status.json").exists() and JobStatus.read(directory).phase == Phase.PREPARING:
            # A crashed preparer may have left a native child writing staging.
            # Absence of its Python task/lease is not proof that child exited.
            raise ValueError("A previous preparation did not settle; inspect this job before retrying or cleaning it up")
        plan_path = directory / "plan.json"
        if plan_path.exists() and UpdatePlan.model_validate_json(plan_path.read_bytes()) != plan:
            raise ValueError("This preparation already belongs to another reviewed plan")
        if not plan_path.exists():
            atomic_write_lines(plan_path, [plan.model_dump_json()])
            plan_path.chmod(0o600)
        # An orphan native command retains this installation-wide lease. Never
        # replace its archive or begin another preparation while it is active.
        with file_access(root / "prepare-native.lock", exclusive=True):
            archive = directory / "worker.pyz"
            archive.unlink(missing_ok=True)  # No committed request exists above.
            _worker_archive(archive)
            process = PreparationProcess.create(directory, plan.installation.environment)
        JobStatus(plan.id, Phase.PREPARING, 0, False,
                  "Checking the installation and preparing the exact package", int(time.time())).save(directory)
        try:
            return await _prepare_inputs(plan, feed, root, directory, process, native_uv=native_uv)
        except asyncio.CancelledError:
            JobStatus(plan.id, Phase.PREPARATION_FAILED, 0, False,
                      "Preparation cancelled after its workers exited; no installation was started",
                      int(time.time())).save(directory)
            raise
        except Exception as exc:
            # Resolver/network exceptions can contain index credentials or paths.
            JobStatus(plan.id, Phase.PREPARATION_FAILED, 0, False,
                      f"Preparation failed ({type(exc).__name__}); no installation was started",
                      int(time.time())).save(directory)
            raise
        finally:
            process.close()


async def _prepare_inputs(plan: UpdatePlan, feed: ReleaseFeed, root: Path, directory: Path,
                          process: PreparationProcess, *, native_uv: bool) -> Path:
    baseline = await shield_and_drain(asyncio.to_thread(inspect_environment, plan.installation.python, uv=native_uv, process=process))
    if (baseline.environment, baseline.python, baseline.app_version, baseline.receipt_sha) != (
        plan.installation.environment, plan.installation.python, plan.installation.installed_version,
        plan.installation.records.get("pyvenv.cfg"),
    ) or any(plan.installation.records.get(name) != digest for name, digest in baseline.app_records.items()):
        raise ValueError("The installation changed since this plan was prepared")
    if native_uv and baseline.manager_receipt_sha != plan.installation.records.get("uv-receipt.toml"):
        raise ValueError("The uv installation settings changed since this plan was prepared")
    if baseline.installer_receipt_sha != plan.installation.records.get(RECEIPT_NAME):
        raise ValueError("The installer selection changed since this plan was prepared")
    validate_profiles(plan.profiles, plan.installation.environment)
    JobStatus(plan.id, Phase.PREPARING, 0, False,
              "Downloading and verifying the reviewed package", int(time.time())).save(directory)
    app_wheel = await feed.download(plan.target, root / "downloads")
    JobStatus(plan.id, Phase.PREPARING, 0, False,
              "Preparing dependencies without changing the installation", int(time.time())).save(directory)
    records, uv = await shield_and_drain(asyncio.to_thread(_prepare_transaction, plan, app_wheel, directory, process))
    current = await shield_and_drain(asyncio.to_thread(inspect_environment, plan.installation.python, uv=native_uv, process=process))
    if current != baseline:
        raise ValueError("Installation changed while preparing the update")
    plan.validate_for(plan.installation)
    plan_path = directory / "plan.json"
    archive = directory / "worker.pyz"
    sources = [BackupSource(str(Path(baseline.environment) / "pyvenv.cfg"))]
    if native_uv:
        sources.append(BackupSource(str(Path(baseline.environment) / "uv-receipt.toml")))
    if baseline.installer_receipt_sha is not None:
        sources.append(BackupSource(str(Path(baseline.environment) / RECEIPT_NAME)))
    for profile in plan.profiles:
        receipt = profile.receipt
        sources.extend(BackupSource.parse({"path": str(path)}) for path in receipt.data_paths)
        sources.append(BackupSource(str(root / "profiles" / f"{receipt.id}.json")))
    spec = WorkerSpec(plan.id, hashlib.sha256(plan_path.read_bytes()).hexdigest(), hashlib.sha256(archive.read_bytes()).hexdigest(),
                      baseline, plan.target.version, records, unique_sources(sources), tuple(plan.restart_profiles), uv,
                      automatic_recovery=bool(plan.restart_profiles) and baseline.installer_receipt_sha is not None)
    for path in [archive, *(directory / "wheels" / item.filename for item in records)]:
        path.chmod(0o600)
        with path.open("r+b") as stream:
            os.fsync(stream.fileno())
    JobStatus(plan.id, Phase.READY, 0, False, "Files prepared; not installed", int(time.time())).save(directory)
    # The immutable request is the commit record: its presence means every
    # input and the initial status were flushed successfully.
    spec.save(directory)
    return directory


def settle_interrupted_preparation(directory: Path) -> JobStatus:
    """Revoke an abandoned, uncommitted preparation after its real child exits.

    Internal recovery only: no install, directory deletion or automatic retry.
    A record from the older parent-only lease scheme cannot establish this proof.
    """
    directory = directory.resolve()
    process = PreparationProcess.load(directory)
    root = installation_state_dir(process.environment)
    with file_access(root / "prepare.lock", exclusive=True), file_access(root / "prepare-native.lock", exclusive=True):
        if PreparationProcess.load(directory) != process:
            raise ValueError("The preparation generation changed")
        status = JobStatus.read(directory)
        if status.phase != Phase.PREPARING or (directory / "request.json").exists() or status.mutation_started:
            raise ValueError("Only an uncommitted preparation can be settled")
        process.close()
        status = JobStatus(directory.name, Phase.PREPARATION_FAILED, 0, False,
                           "Interrupted preparation stopped; no installation was started", int(time.time()))
        status.save(directory)
        return status


async def start_job(directory: Path, feed: ReleaseFeed, *, repair: bool = False) -> subprocess.Popen[bytes]:
    """Approve the exact staged job and start its detached worker.

    Not called by a client route yet. The caller must quiesce/stop old runtimes;
    the worker rechecks their leases before installation. Only explicitly saved
    background participants may be restarted, never an external supervisor.
    """
    spec = WorkerSpec.read(directory)
    plan = UpdatePlan.model_validate_json((directory / "plan.json").read_bytes())
    runtime_phases = {Phase.RESTARTING, Phase.ACTIVATING, Phase.FINALIZING, Phase.RESTART_FAILED}
    if JobStatus.read(directory).phase not in runtime_phases:
        await feed.revalidate(plan.target)
    with (file_access(installation_state_dir(spec.baseline.environment) / "channel.lock", exclusive=False),
          file_access(installation_state_dir(spec.baseline.environment) / "worker.lock", exclusive=True)):
        state = JobStatus.read(directory)
        if state.phase in {Phase.INSTALLED, Phase.CANCELLED, Phase.SUCCEEDED, Phase.RESTORED}:
            raise ValueError("This job is already finished; it cannot be started again")
        restarting = state.phase in runtime_phases
        if state.mutation_started and not repair:
            raise ValueError("This interrupted job requires an explicit repair confirmation")
        if repair and not state.mutation_started:
            raise ValueError("Repair is only available after this job began replacing files")
        current = await shield_and_drain(asyncio.to_thread(inspect_job_environment, directory, spec))
        with (installation_access(updating=not restarting, allow_incomplete=restarting,
                                  environment=spec.baseline.environment),
              nullcontext() if state.phase == Phase.FINALIZING else
              data_access((source.path for source in spec.backup_sources), updating=not restarting, job_id=spec.plan_id)):
            check_environment(spec, repairing=state.mutation_started, current=current)
            if not restarting:
                require_stopped_profiles(plan.profiles, spec.baseline.environment)
            spec.verify_inputs(directory)
            now = int(time.time())
            if not repair:
                plan.validate_for(plan.installation, now=now)
            write_record(directory / "approval.json", {
                "plan_id": spec.plan_id, "request_sha256": hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
                "created_at": now, "expires_at": now + 900 if repair else min(plan.expires_at, now + 900),
            })
    return _spawn_worker(directory, spec)


def start_handoff(directory: Path, *, once: bool = False) -> subprocess.Popen[bytes] | None:
    """Confirm an exact prepared plan and detach before the requesting gateway exits.

    Unlike start_job (already-stopped installations/repair), release revalidation
    and cooperative shutdown run independently of the caller. No installation
    approval is written until that child exits and exclusive leases are held.
    With once=True, persist one confirmation and never launch again for a repeated
    request. A missing response, failed launch or failed job is not retry authority.
    """
    return _start_handoff(directory, once=once)


def retry_handoff(directory: Path, previous_confirmation_id: str) -> subprocess.Popen[bytes] | None:
    """Consume explicit recovery consent for one unmodified handoff generation.

    A stale predecessor is a read, not another retry. A live owner, surviving
    preflight child, expired plan or package mutation requires a different action.
    """
    if UUID(previous_confirmation_id).hex != previous_confirmation_id:
        raise ValueError("Invalid previous execution confirmation")
    return _start_handoff(directory, once=True, previous_confirmation_id=previous_confirmation_id)


def _start_handoff(directory: Path, *, once: bool,
                   previous_confirmation_id: str | None = None) -> subprocess.Popen[bytes] | None:
    spec = WorkerSpec.read(directory)
    plan = UpdatePlan.model_validate_json((directory / "plan.json").read_bytes())
    root = installation_state_dir(spec.baseline.environment)

    def already_confirmed() -> bool:
        current = ExecutionConfirmation.read(directory)
        if previous_confirmation_id is not None:
            if current is None:
                raise ValueError("No execution confirmation is available to retry")
            return current.id != previous_confirmation_id
        return once and current is not None

    if already_confirmed():
        return None
    confirmation = None
    with (file_access(root / "supervisor.lock", exclusive=True) if spec.automatic_recovery else nullcontext(),
          file_access(root / "channel.lock", exclusive=False),
          file_access(root / "worker.lock", exclusive=True),
          file_access(root / "handoff-child.lock", exclusive=True),
          installation_access(environment=spec.baseline.environment)):
        state = JobStatus.read(directory)
        if already_confirmed():
            return None
        if once and previous_confirmation_id is None and state.phase != Phase.READY:
            raise ValueError("Only a ready job can receive its first execution confirmation")
        if state.mutation_started or state.phase not in {
            Phase.READY, Phase.CHECKING, Phase.STOPPING, Phase.HANDOFF_FAILED,
        }:
            raise ValueError("Shutdown handoff requires an unmodified prepared job")
        now = int(time.time())
        plan.validate_for(plan.installation, now=now)
        spec.verify_inputs(directory)
        approval: dict[str, object] = {
            "plan_id": spec.plan_id, "request_sha256": hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
            "created_at": now, "expires_at": min(plan.expires_at, now + 900),
        }
        if once:
            confirmation = ExecutionConfirmation(
                uuid4().hex, spec.plan_id, hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
                now, min(plan.expires_at, now + 900),
            )
            # Persist before any launch. If the requester dies here, repeated
            # submissions read this record; recovery needs explicit new consent.
            confirmation.save(directory)
            approval["confirmation_id"] = confirmation.id
            # Both owner leases are held. Revoking the old confirmation first
            # makes its delayed launchers harmless, even across a crash here.
            (directory / "confirmation-claimed.json").unlink(missing_ok=True)
        write_record(directory / "handoff-approval.json", approval)
        (directory / "approval.json").unlink(missing_ok=True)
        JobStatus(spec.plan_id, Phase.CHECKING, state.attempt, False,
                  "Starting an independent update handoff", now).save(directory)
    # Release the ownership lease before spawning: a fast child must be able to
    # take it immediately. Duplicate launches still serialize in run_job.
    try:
        return _spawn_worker(directory, spec, handoff=True, confirmation_id=confirmation.id if confirmation else None)
    except OSError:
        with file_access(root / "worker.lock", exclusive=True):
            state = JobStatus.read(directory)
            current = ExecutionConfirmation.read(directory)
            if (state.phase == Phase.CHECKING
                    and (confirmation is None or current == confirmation)):
                JobStatus(spec.plan_id, Phase.HANDOFF_FAILED, state.attempt, False,
                          "Could not start the independent update process; no shutdown was requested",
                          int(time.time())).save(directory)
        raise


def _spawn_worker(directory: Path, spec: WorkerSpec, *, handoff: bool = False,
                  confirmation_id: str | None = None) -> subprocess.Popen[bytes]:
    command = [spec.baseline.base_python, "-I", "-S", str(directory / "worker.pyz")]
    if spec.automatic_recovery:
        command.extend(["--supervise", str(directory)])
    if confirmation_id is not None:
        command.extend(["--confirmed-handoff", str(directory), confirmation_id])
    else:
        command.extend(["--handoff", str(directory)] if handoff else [str(directory)])
    if os.name == "nt":
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                cwd=directory, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            cwd=directory, start_new_session=True)
