"""Post-install handoff to reviewed, explicitly managed background gateways.

Entered through the frozen worker while holding a shared installation lease. The
coordinator grants scoped data initialization, verifies all parked runtimes, then
durably authorizes those exact run identities to accept work. It never reinstalls
packages, kills another owner, or invents launch options from resolved paths.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import nanobot
from nanobot.data_access import (
    DataStartupGrant,
    data_access,
    finish_data_handoff,
)
from nanobot.gateway.runtime import GatewayHealthIdentity, GatewayRuntime
from nanobot.installation_lock import pending_update_path
from nanobot.update_plan import UpdatePlan
from nanobot.update_profiles import (
    ProfileReceipt,
    inspect_profiles,
    validate_restart_identity,
    verify_restarted_profile,
)
from nanobot.update_worker import JobStatus, Phase, WorkerSpec, read_record, write_record

_TOKEN_ENV = "NANOBOT_UPDATE_STARTUP_TOKEN"
_HANDOFF_PHASES = {Phase.RESTARTING, Phase.ACTIVATING, Phase.FINALIZING, Phase.RESTART_FAILED, Phase.SUCCEEDED, Phase.RESTORED}


def _read_plan(directory: Path) -> tuple[WorkerSpec, UpdatePlan]:
    spec = WorkerSpec.read(directory)
    if (directory / "restoration.json").exists():
        restoration = read_record(directory / "restoration.json")
        if restoration != {"plan_id": spec.plan_id, "state": "restarting"}:
            raise ValueError("The original program restoration has not completed")
        spec = replace(spec, version=spec.baseline.app_version)
    plan = UpdatePlan.model_validate_json((directory / "plan.json").read_bytes())
    if (Path(sys.prefix).resolve() != Path(spec.baseline.environment)
            or nanobot.__version__ != spec.version or plan.id != spec.plan_id
            or tuple(plan.restart_profiles) != spec.restart_profiles or not spec.restart_profiles):
        raise ValueError("Runtime handoff does not match the approved installation and target")
    return spec, plan


@dataclass(frozen=True)
class GatewayStartup:
    directory: Path
    previous: ProfileReceipt
    grant: DataStartupGrant

    def validate_installation(self) -> None:
        spec, plan = _read_plan(self.directory)
        pending = read_record(pending_update_path())
        selected = {item.receipt.id: item.receipt for item in plan.profiles}
        if (pending.get("job_id") != self.grant.job_id or pending.get("version") != spec.version
                or spec.plan_id != self.grant.job_id or self.grant.participant != self.previous.id
                or self.previous.id not in spec.restart_profiles
                or selected.get(self.previous.id) != self.previous
                or JobStatus.read(self.directory).phase not in {Phase.RESTARTING, Phase.ACTIVATING}):
            raise ValueError("This gateway has no current protected-startup handoff")

    def validate_profile(self, current: ProfileReceipt) -> None:
        validate_restart_identity(self.previous, current, version=nanobot.__version__, job_id=self.grant.job_id)

    async def wait_for_activation(self, identity: GatewayHealthIdentity) -> None:
        """An approval for an earlier attempt/run cannot activate this process."""
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            status = JobStatus.read(self.directory)
            if status.phase not in {Phase.RESTARTING, Phase.ACTIVATING, Phase.FINALIZING, Phase.SUCCEEDED, Phase.RESTORED}:
                raise ValueError("Update handoff stopped before gateway activation")
            try:
                decision = read_record(self.directory / "activation.json")
            except FileNotFoundError:
                decision = {}
            if (status.phase in {Phase.ACTIVATING, Phase.FINALIZING, Phase.SUCCEEDED, Phase.RESTORED}
                    and decision.get("plan_id") == self.grant.job_id
                    and decision.get(self.previous.id) == asdict(identity)):
                return
            await asyncio.sleep(0.1)
        raise TimeoutError("Gateway activation was not verified in time")


def run_gateway(directory: Path, participant: str) -> None:
    # Remove the bearer before configuration, channels, MCP or tools can inherit it.
    token = os.environ.pop(_TOKEN_ENV, "")
    spec, plan = _read_plan(directory)
    previous = next(item.receipt for item in plan.profiles if item.receipt.id == participant)
    startup = GatewayStartup(directory, previous, DataStartupGrant(spec.plan_id, participant, token))
    startup.validate_installation()
    launch = previous.launch
    if launch is None:
        raise ValueError("Original gateway launch selectors are unavailable")

    from nanobot.cli.entry import configure_windows_console
    from nanobot.cli.gateway_runtime import _run_gateway
    from nanobot.cli.process_identity import set_cli_process_identity
    from nanobot.cli.runtime_config import _load_runtime_config
    from nanobot.config.home import set_home_path
    from nanobot.config.loader import get_config_path
    from nanobot.gateway.runtime import GatewayInstance
    from nanobot.utils.log_config import configure_console_logging
    from nanobot.utils.rotating_output import configure_background_output_from_env

    configure_background_output_from_env()
    set_cli_process_identity(["gateway"])
    configure_windows_console()
    configure_console_logging(sys.stderr, level="DEBUG" if launch.verbose else "INFO")
    if Path.cwd().resolve() != Path(launch.working_directory):
        raise ValueError("Gateway restart used a different working directory")
    set_home_path(Path(launch.home) if launch.home else None)
    config = _load_runtime_config(launch.config_path, launch.workspace)
    instance = GatewayInstance.resolve(config_path=get_config_path(), workspace=launch.workspace)
    _run_gateway(config, port=previous.port, verbose=launch.verbose, gateway_instance=instance,
                 update_startup=startup)


def _start_gateway(directory: Path, previous: ProfileReceipt, grant: DataStartupGrant) -> None:
    launch = previous.launch
    if launch is None:
        raise ValueError("Original gateway launch selectors are unavailable")

    def spawn(_command: list[str], **kwargs: Any) -> subprocess.Popen[bytes] | subprocess.Popen[str]:
        # Preserve the existing runtime's detached-process and rotating-log setup.
        kwargs["env"] = {**kwargs["env"], _TOKEN_ENV: grant.token}
        return subprocess.Popen([previous.python, "-I", "-S", str(directory / "worker.pyz"),
                                 "--gateway", str(directory), previous.id],
                                cwd=launch.working_directory, text=False, **kwargs)

    runtime = GatewayRuntime(paths=previous.runtime_paths,
                             python_executable=previous.python, popen=spawn)
    result = runtime.start_background(launch.options(port=previous.port))
    if not result.ok:
        raise ValueError("The reviewed gateway could not start; inspect its existing runtime log")


def _wait_verified(profiles: list[ProfileReceipt], spec: WorkerSpec, *,
                   maintenance: bool | None, deadline: float) -> list[ProfileReceipt]:
    while True:
        try:
            return [verify_restarted_profile(profile, version=spec.version, job_id=spec.plan_id,
                                             maintenance=maintenance) for profile in profiles]
        except ValueError:
            if time.monotonic() >= deadline:
                raise ValueError("The reviewed gateways did not confirm target-version readiness in time") from None
            time.sleep(0.1)


def run_restarts(directory: Path) -> None:
    """Resume only this job's startup/activation; never rerun its pip transaction."""
    spec, plan = _read_plan(directory)
    status = JobStatus.read(directory)
    if status.phase not in _HANDOFF_PHASES:
        raise ValueError("Package verification has not handed off to gateway restart")
    profiles = [item.receipt for item in plan.profiles if item.receipt.id in spec.restart_profiles]
    deadline = time.monotonic() + 120
    pending = pending_update_path()
    restored = (directory / "restoration.json").exists()
    final_phase = Phase.RESTORED if restored else Phase.SUCCEEDED
    final_message = ("The original service is running; the update was not installed and user data was not restored"
                     if restored else "The reviewed gateways are running the verified target version")
    if status.phase in {Phase.SUCCEEDED, Phase.RESTORED}:
        # Completed jobs are history, not authority to relaunch stopped gateways.
        return
    if pending.exists() and read_record(pending).get("job_id") != spec.plan_id:
        raise ValueError("The installation is reserved by another update")
    if status.phase == Phase.FINALIZING:
        # Verification was durably committed before either fence was cleared.
        # Do not rerun or reactivate applications to recover only this cleanup.
        finish_data_handoff((item.path for item in spec.backup_sources), job_id=spec.plan_id)
        pending.unlink(missing_ok=True)
        status.advance(directory, final_phase, final_message)
        return
    if not pending.exists():
        raise ValueError("The runtime handoff no longer owns an installation fence")

    with data_access((item.path for item in spec.backup_sources), job_id=spec.plan_id) as data:
        observed = {item.receipt.id: item for item in inspect_profiles(spec.baseline.environment)}
        if set(observed) != {item.receipt.id for item in plan.profiles}:
            raise ValueError("Gateway inventory changed during the update")
        # Do not start or ignore a newly changed, unreviewed runtime.
        for item in plan.profiles:
            current = observed[item.receipt.id]
            previous = item.receipt
            unchanged = (current.receipt.model_dump(exclude={"active"})
                         == previous.model_dump(exclude={"active"}))
            if previous.id not in spec.restart_profiles:
                if not unchanged or current.state != "stopped":
                    raise ValueError("An unselected gateway changed during the update")
            elif current.state == "unconfirmed":
                raise ValueError("The restart participant's process owner is unconfirmed")
            elif not unchanged:
                # A failed, parked candidate may have recorded its run before
                # exiting. Its stopped receipt is history, not launch authority.
                version = plan.target.version if restored and current.state == "stopped" else spec.version
                validate_restart_identity(previous, current.receipt, version=version, job_id=spec.plan_id)
            elif current.state != "stopped":
                raise ValueError("An original gateway is still running")

        status.advance(directory, Phase.RESTARTING, "Starting the reviewed gateways with task intake closed", mutation_started=True)
        for previous in profiles:
            if observed[previous.id].state == "stopped":
                grant = data.grant_profile_startup(
                    previous.id, home=Path(previous.home), data_dir=Path(previous.data_dir),
                    config=Path(previous.config), workspace=Path(previous.workspace),
                )
                _start_gateway(directory, previous, grant)

        # A resumed activation can include already active runs; their durable
        # job identity still has to match. A fresh handoff must prove intake shut.
        resuming_activation = (directory / "activation.json").exists()
        parked = _wait_verified(profiles, spec, maintenance=None if resuming_activation else True, deadline=deadline)
        status.advance(directory, Phase.ACTIVATING, "Verified runtime identities; enabling the reviewed gateways", mutation_started=True)
        write_record(directory / "activation.json", {
            "plan_id": spec.plan_id, **{item.id: asdict(item.health_identity) for item in parked},
        })
        _wait_verified(profiles, spec, maintenance=False, deadline=deadline)
        status.advance(directory, Phase.FINALIZING, "Verified running gateways; completing maintenance cleanup", mutation_started=True)
        # Clearing data first retains the installation fence if either operation
        # fails. Active participants continue holding their own shared leases.
        data.release_reservation()
        pending.unlink()
        status.advance(directory, final_phase, final_message)
