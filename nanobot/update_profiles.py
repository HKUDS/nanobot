"""Installation-scoped inventory of gateway profiles, not process-control authority.

Receipts survive shutdown so a stopped profile's durable data is not forgotten by
an update plan. Liveness is checked against the existing process identity, never a
PID alone. This inventory cannot discover pre-receipt or other-account runtimes;
the installation lease and an explicit process-owner handoff are still required.
"""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator

import nanobot
from nanobot.config.home import get_home_path
from nanobot.data_access import DataStartupGrant, profile_data_access, profile_data_paths
from nanobot.gateway.runtime import (
    GatewayHealthIdentity,
    GatewayInstance,
    GatewayRuntime,
    GatewayRuntimePaths,
    GatewayStartOptions,
)
from nanobot.installation_lock import installation_state_dir
from nanobot.utils.atomic_file import atomic_write_lines, read_atomic_bytes


class ProfileLaunch(BaseModel):
    """Original selectors, not inferred arguments or an executable shell command."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    home: str | None
    config_path: str | None
    workspace: str | None
    working_directory: str
    verbose: bool
    lifetime: Literal["explicit", "on_demand"]

    @field_validator("home", "config_path", "workspace", "working_directory")
    @classmethod
    def bounded_path(cls, value: str | None) -> str | None:
        if value is not None and (not Path(value).is_absolute() or len(value) > 4096 or "\0" in value):
            raise ValueError("Launch selectors must be bounded absolute paths")
        return value

    def options(self, *, port: int) -> GatewayStartOptions:
        return GatewayStartOptions(home=self.home, config_path=self.config_path,
                                   workspace=self.workspace, port=port, verbose=self.verbose)


class ProfileReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    environment: str
    python: str
    package: str
    version: str
    home: str
    data_dir: str
    config: str
    workspace: str
    state_path: str
    log_path: str
    port: int = Field(ge=0, le=65535)
    launch_mode: Literal["foreground", "background", "unknown"]
    pid: int = Field(gt=0)
    process_identity: str | int | None
    active: bool
    # Older receipts remain useful data inventory, but cannot prove launch intent.
    launch: ProfileLaunch | None = None
    stop_protocol: Literal[1] | None = None
    update_job_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")

    @field_validator("environment", "python", "package", "home", "data_dir", "config", "workspace", "state_path", "log_path")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if not Path(value).is_absolute() or len(value) > 4096 or "\0" in value:
            raise ValueError("Profile paths must be bounded absolute paths")
        return value

    @property
    def health_identity(self) -> GatewayHealthIdentity:
        return GatewayHealthIdentity(self.id, self.run_id, self.version)

    @property
    def runtime_paths(self) -> GatewayRuntimePaths:
        state, log = Path(self.state_path), Path(self.log_path)
        return GatewayRuntimePaths(run_dir=state.parent, logs_dir=log.parent, state_path=state, log_path=log)

    @property
    def data_paths(self) -> tuple[Path, ...]:
        # Preserve individual store paths: leases and backups must reject links,
        # not resolve them into additional read/write authority.
        return profile_data_paths(home=Path(self.home), data_dir=Path(self.data_dir),
                                  config=Path(self.config), workspace=Path(self.workspace))


class ObservedProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    receipt: ProfileReceipt
    state: Literal["running", "stopped", "unconfirmed"]


class _RuntimeClaim(BaseModel):
    model_config = ConfigDict(strict=True)
    pid: int = Field(gt=0)
    identity: str | int | None = None
    stable_identity: str | int | None = None


def _observe(receipt: ProfileReceipt) -> Literal["running", "stopped", "unconfirmed"]:
    state_path = Path(receipt.state_path)
    runtime = GatewayRuntime(paths=receipt.runtime_paths)
    try:
        if state_path.is_symlink() or state_path.stat().st_size > 32 * 1024:
            return "unconfirmed"
        claim = _RuntimeClaim.model_validate_json(read_atomic_bytes(state_path))
    except FileNotFoundError:
        claim = None
    except (OSError, ValueError):
        return "unconfirmed"
    if claim is not None and runtime.process_is_running(claim.pid):
        identity = claim.stable_identity if claim.stable_identity is not None else claim.identity
        if identity is None:
            return "unconfirmed"
        match = runtime.process_identity_match(identity, claim.pid)
        if match == "unknown":
            return "unconfirmed"
        if match == "match":
            # The profile may now be used by a different installation. Its old
            # inactive receipt does not grant a right to back up/restore live data.
            if claim.pid != receipt.pid:
                return "unconfirmed"
            if receipt.process_identity is None:
                return "unconfirmed"
            own_match = runtime.process_identity_match(receipt.process_identity, receipt.pid)
            if own_match != "match":
                return "unconfirmed"
            return "running" if receipt.active else "stopped"
    if receipt.active and runtime.process_is_running(receipt.pid):
        match = (runtime.process_identity_match(receipt.process_identity, receipt.pid)
                 if receipt.process_identity is not None else "unknown")
        if match != "mismatch":
            return "unconfirmed"  # Live process, but its runtime claim disappeared.
    return "stopped"


def _profile_id(state_path: str) -> str:
    return hashlib.sha256(os.fsencode(Path(state_path).resolve())).hexdigest()


def _save(directory: Path, receipt: ProfileReceipt) -> None:
    path = directory / f"{receipt.id}.json"
    atomic_write_lines(path, [receipt.model_dump_json()])
    path.chmod(0o600)


@contextmanager
def record_gateway_profile(instance: GatewayInstance, runtime: GatewayRuntime, *,
                           data_dir: Path, workspace: Path, port: int,
                           verbose: bool = False,
                           grant: DataStartupGrant | None = None,
                           cooperative_stop: bool = False) -> Generator[ProfileReceipt]:
    """Record an already-claimed gateway and retain its profile after shutdown."""
    state_path = str(instance.paths.state_path.resolve())
    directory = installation_state_dir() / "profiles"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    status = runtime.status()
    if not status.running or status.pid != os.getpid():
        raise ValueError("Only the gateway that claimed this runtime may record its profile")
    options = instance.start_options(port=port, verbose=verbose)
    receipt = ProfileReceipt(
        id=_profile_id(state_path), run_id=uuid4().hex,
        environment=str(Path(sys.prefix).resolve()), python=str(Path(sys.executable).absolute()),
        package=str(Path(nanobot.__file__).resolve()), version=nanobot.__version__,
        home=str(get_home_path().resolve()), data_dir=str(data_dir.resolve()),
        config=str(instance.config_path.resolve()), workspace=str(workspace.resolve()),
        state_path=state_path, log_path=str(instance.paths.log_path.resolve()), port=port,
        launch_mode=status.launch_mode, pid=os.getpid(),
        process_identity=runtime.process_identity(os.getpid()), active=True,
        update_job_id=grant.job_id if grant else None,
        stop_protocol=1 if cooperative_stop else None,
        launch=ProfileLaunch(home=options.home, config_path=options.config_path,
                             workspace=options.workspace, working_directory=str(Path.cwd().resolve()),
                             verbose=options.verbose, lifetime=status.lifetime),
    )
    if grant is not None and grant.participant != receipt.id:
        raise ValueError("Startup grant belongs to a different gateway instance")
    with profile_data_access(home=Path(receipt.home), data_dir=Path(receipt.data_dir),
                             config=Path(receipt.config), workspace=Path(receipt.workspace), grant=grant):
        with FileLock(str(directory / "profiles.lock"), timeout=5):
            _save(directory, receipt)
        try:
            yield receipt
        finally:
            with FileLock(str(directory / "profiles.lock"), timeout=5):
                # Persist the inactive receipt before releasing the data leases.
                # A receipt alone does not prove every external writer has stopped.
                _save(directory, receipt.model_copy(update={"active": False}))


def inspect_profiles(environment: str) -> list[ObservedProfile]:
    """Read known profiles without writing their runtime files or contacting hosts."""
    directory = installation_state_dir(environment) / "profiles"
    if not directory.exists():
        return []
    profiles: list[ObservedProfile] = []
    with FileLock(str(directory / "profiles.lock"), timeout=5):
        for path in sorted(directory.glob("*.json")):
            if len(profiles) >= 1024 or path.is_symlink() or path.stat().st_size > 32 * 1024:
                raise ValueError("Invalid installation profile inventory")
            receipt = ProfileReceipt.model_validate_json(read_atomic_bytes(path))
            if (receipt.environment != str(Path(environment).resolve()) or
                receipt.id != path.stem or receipt.id != _profile_id(receipt.state_path)):
                raise ValueError("Profile receipt belongs to a different installation or instance")
            profiles.append(ObservedProfile(receipt=receipt, state=_observe(receipt)))
    return profiles


def validate_profiles(expected: list[ObservedProfile], environment: str) -> None:
    """Before confirming a plan, reject a newly started/reconfigured profile."""
    if inspect_profiles(environment) != expected:
        raise ValueError("Gateway profiles changed since this plan; check again before confirming")


def require_stopped_profiles(expected: list[ObservedProfile], environment: str) -> None:
    """Allow the reviewed gateways to exit, not a replacement or an unknown owner."""
    current = inspect_profiles(environment)
    # A graceful exit only changes `active`; a restart/reconfiguration creates a
    # new run_id and needs a new plan even if the file paths are unchanged.
    before = [item.receipt.model_dump(exclude={"active"}) for item in expected]
    after = [item.receipt.model_dump(exclude={"active"}) for item in current]
    if before != after:
        raise ValueError("Gateway profiles changed since this plan; check again before confirming")
    if any(item.state != "stopped" for item in current):
        raise ValueError("A reviewed gateway profile is still in use or its process owner is unconfirmed")


def validate_restart_identity(previous: ProfileReceipt, current: ProfileReceipt, *,
                              version: str, job_id: str | None = None) -> None:
    """Validate a new claim without mistaking it for running/healthy evidence."""
    if previous.launch is None:
        raise ValueError("The original gateway launch identity is unknown")
    changing = {"run_id", "pid", "process_identity", "version", "active", "update_job_id", "stop_protocol"}
    if (current.model_dump(exclude=changing) != previous.model_dump(exclude=changing)
            or current.version != version or current.run_id == previous.run_id
            or current.process_identity == previous.process_identity or current.update_job_id != job_id):
        raise ValueError("The restarted gateway differs from the reviewed instance or target version")


def verify_restarted_profile(previous: ProfileReceipt, *, version: str,
                             job_id: str | None = None, maintenance: bool | None = None) -> ProfileReceipt:
    """Verify a fresh run of the reviewed local profile; never start/stop it.

    Call under the update owner's lifecycle/maintenance handoff. A receipt or an
    HTTP 200 alone is insufficient, and this does not grant restart authority.
    """
    observed = next((item for item in inspect_profiles(previous.environment)
                     if item.receipt.id == previous.id), None)
    if observed is None or observed.state != "running":
        raise ValueError("The updated gateway is not running with a verified process identity")
    current = observed.receipt
    validate_restart_identity(previous, current, version=version, job_id=job_id)
    runtime = GatewayRuntime(paths=current.runtime_paths)
    if not runtime.verify_ready(current.health_identity, maintenance=maintenance):
        raise ValueError("Gateway readiness did not confirm the updated instance, run and version")
    # Re-read the receipt as well: a new claim can precede its new receipt.
    final = next((item for item in inspect_profiles(previous.environment)
                  if item.receipt.id == previous.id), None)
    if final != observed:
        raise ValueError("The gateway changed during restart verification")
    return current
