"""Cooperative pre-install shutdown of explicitly reviewed gateway runs.

The private local mailbox carries identities, never commands or arbitrary paths.
Preparation is reversible: every participant must hold its idle admission gate
before the coordinator commits normal shutdown. A committed stop is not an
installation approval, and the installer must still acquire exclusive leases.
Only a detached update owner runs this protocol, never a request awaiting its own exit.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from nanobot.gateway.runtime import GatewayRuntime
from nanobot.installation_lock import file_access, installation_access, installation_state_dir
from nanobot.runtime_admission import RuntimeBusyError, RuntimeMaintenanceError
from nanobot.update_plan import UpdatePlan
from nanobot.update_profiles import ProfileReceipt, require_stopped_profiles, validate_profiles
from nanobot.update_worker import JobStatus, Phase, WorkerSpec, read_record, write_record
from nanobot.utils.atomic_file import io_path, read_atomic_bytes

_POLL_SECONDS = 0.1


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    plan_id: str = Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    attempt: str = Field(pattern=r"^[0-9a-f]{32}$")
    phase: Literal["prepare", "commit", "abort", "stopped"]
    # Monotonic timestamps coordinate processes on this host, not other hosts.
    deadline: float = Field(gt=0, allow_inf_nan=False)


class _Reply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    attempt: str = Field(pattern=r"^[0-9a-f]{32}$")
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    state: Literal["ready", "busy", "released", "stopping", "refused"]


def _request_path(environment: str) -> Path:
    return installation_state_dir(environment) / "stop.json"


def _read_request(environment: str) -> _Request | None:
    try:
        return _Request.model_validate(read_record(_request_path(environment), max_bytes=2048))
    except FileNotFoundError:
        return None


def _job(environment: str, identifier: str) -> tuple[Path, UpdatePlan]:
    directory = installation_state_dir(environment) / "jobs" / identifier
    spec = WorkerSpec.read(directory)
    plan = UpdatePlan.model_validate_json(read_atomic_bytes(directory / "plan.json"))
    status = JobStatus.read(directory)
    if (spec.baseline.environment != environment or plan.installation.environment != environment
            or spec.plan_id != plan.id or tuple(plan.restart_profiles) != spec.restart_profiles
            or spec.version != plan.target.version
            or status.phase not in {Phase.READY, Phase.CHECKING, Phase.STOPPING} or status.mutation_started):
        raise ValueError("Gateway shutdown requires an unchanged, prepared update job")
    return directory, plan


def _reply(directory: Path, request: _Request, profile: ProfileReceipt,
           state: Literal["ready", "busy", "released", "stopping", "refused"]) -> None:
    path = directory / "stop-replies" / f"{profile.id}.json"
    io_path(path.parent).mkdir(exist_ok=True, mode=0o700)
    write_record(path, _Reply(attempt=request.attempt, run_id=profile.run_id, state=state).model_dump())


def _coordinator_present(environment: str) -> bool:
    try:
        with file_access(installation_state_dir(environment) / "stop.lock", exclusive=True):
            return False
    except BlockingIOError:
        return True


async def watch_gateway_stop(
    profile: ProfileReceipt,
    maintenance: Callable[[], AbstractContextManager[None]],
    shutdown_event: asyncio.Event,
    shutdown_gate: ExitStack,
) -> None:
    """Serve this run's mailbox on the same event loop as task admission.

    The runtime must retain shutdown_gate until its consumers and cleanup finish.
    Cancellation before commit restores intake; after commit the outer runtime
    owns the gate, so cancelling this watcher cannot reopen task intake.
    """
    seen: str | None = None
    while not shutdown_event.is_set():
        try:
            request = _read_request(profile.environment)
            if request is not None and request.attempt != seen:
                seen = request.attempt
                if (request.phase == "prepare" and time.monotonic() < request.deadline
                        and _coordinator_present(profile.environment)):
                    await _prepare_gateway_stop(profile, request, maintenance, shutdown_event, shutdown_gate)
        except (OSError, ValueError):
            # A malformed/stale local record must not crash an otherwise healthy
            # gateway. The coordinator times out; it never treats silence as ready.
            pass
        await asyncio.sleep(_POLL_SECONDS)


async def _prepare_gateway_stop(
    profile: ProfileReceipt,
    request: _Request,
    maintenance: Callable[[], AbstractContextManager[None]],
    shutdown_event: asyncio.Event,
    shutdown_gate: ExitStack,
) -> None:
    directory, plan = _job(profile.environment, request.plan_id)
    selected = next((item for item in plan.profiles if item.receipt.id == profile.id), None)
    if profile.id not in plan.stop_profiles:
        return
    if selected is None or selected.receipt != profile or selected.state != "running":
        _reply(directory, request, profile, "refused")
        return
    plan.validate_for(plan.installation)
    committed = False
    with ExitStack() as gate:
        try:
            gate.enter_context(maintenance())
        except (RuntimeBusyError, RuntimeMaintenanceError):
            _reply(directory, request, profile, "busy")
            return
        try:
            _reply(directory, request, profile, "ready")
            while not shutdown_event.is_set():
                current = _read_request(profile.environment)
                if (current is None or current.plan_id != request.plan_id
                        or current.attempt != request.attempt or current.phase not in {"prepare", "commit"}):
                    return
                if current.phase == "commit":
                    # Commit is durable and irrevocable even if its coordinator
                    # exits. Only a prepared run can accept it; startup replay
                    # or a new run identity cannot enter this branch.
                    shutdown_gate.enter_context(gate.pop_all())
                    committed = True
                    shutdown_event.set()
                    _reply(directory, request, profile, "stopping")
                    return
                if not _coordinator_present(profile.environment):
                    # The owner may have committed just before exiting. Read
                    # once more after observing its released lease, rather than
                    # undoing that durable decision from an earlier prepare read.
                    latest = _read_request(profile.environment)
                    if (latest is not None and latest.attempt == request.attempt
                            and latest.plan_id == request.plan_id and latest.phase == "commit"):
                        continue
                    return
                # While its lease remains held, the coordinator owns the
                # deadline decision. Independently expiring a ready participant
                # could reopen intake between the ready check and commit.
                await asyncio.sleep(_POLL_SECONDS)
        finally:
            if not committed:
                # Release before publishing the acknowledgement. A failed write
                # cannot keep task intake closed after refusal/cancellation.
                gate.close()
                _reply(directory, request, profile, "released")


async def stop_reviewed_gateways(directory: Path, *, timeout: float = 30) -> None:
    """Stop only the plan's selected runs, or abort before any stop is committed.

    Call from the detached update owner, not a gateway request awaiting its own
    shutdown. Cancellation before commit aborts all holds. After commit, callers
    must report/recover the saved handoff rather than promise that nobody stopped.
    The caller revalidates release eligibility and installation identity before
    requesting shutdown. This operation neither approves nor launches installation.
    """
    if not 0 < timeout <= 120:
        raise ValueError("Shutdown timeout must be between zero and 120 seconds")
    spec = WorkerSpec.read(directory)
    environment = spec.baseline.environment
    root = installation_state_dir(environment)
    # The detached parent owns worker.lock. This coordinator owns the stop
    # mailbox and a runtime lease instead, also protecting standalone callers
    # and an orphan child when its parent exits before the handoff completes.
    with (installation_access(environment=environment), file_access(root / "stop.lock", exclusive=True),
          file_access(root / "prepare.lock", exclusive=True), file_access(root / "prepare-native.lock", exclusive=True)):
        _, plan = _job(environment, spec.plan_id)
        participants = [item.receipt for item in plan.profiles if item.receipt.id in plan.stop_profiles]
        if any(item.pid == os.getpid() for item in participants):
            raise ValueError("The shutdown coordinator must run outside the selected gateways")
        previous = _read_request(environment)
        resuming = previous is not None and previous.plan_id == plan.id and previous.phase in {"commit", "stopped"}
        if previous is not None and previous.phase == "commit" and not resuming:
            raise ValueError("A committed gateway shutdown needs to be resolved before another handoff")
        if not resuming:
            plan.validate_for(plan.installation)
            # Refuse missing/changed staged inputs before disturbing a running
            # gateway. Installation will independently recheck them after exit.
            await asyncio.to_thread(spec.verify_inputs, directory)
            plan.validate_for(plan.installation)
            validate_profiles(plan.profiles, environment)
            if any(item.state == "unconfirmed" or
                   (item.state == "running" and item.receipt.id not in plan.stop_profiles)
                   for item in plan.profiles):
                raise ValueError("Every running gateway must have a confirmed shutdown selection")
            request = _Request(plan_id=plan.id, attempt=uuid4().hex, phase="prepare",
                               deadline=time.monotonic() + timeout)
            write_record(_request_path(environment), request.model_dump())
            try:
                while True:
                    ready: set[str] = set()
                    for profile in participants:
                        path = directory / "stop-replies" / f"{profile.id}.json"
                        try:
                            reply = _Reply.model_validate(read_record(path, max_bytes=2048))
                        except FileNotFoundError:
                            continue
                        if reply.attempt != request.attempt:
                            continue
                        if reply.run_id != profile.run_id:
                            raise ValueError("A selected gateway run changed; no stop was committed")
                        if reply.state != "ready":
                            raise ValueError("A selected gateway is busy or refused shutdown; no stop was committed")
                        ready.add(profile.id)
                    if len(ready) == len(participants):
                        plan.validate_for(plan.installation)
                        validate_profiles(plan.profiles, environment)
                        if time.monotonic() >= request.deadline:
                            raise TimeoutError("Gateway shutdown preparation expired")
                        write_record(_request_path(environment), request.model_copy(update={"phase": "commit"}).model_dump())
                        break
                    if time.monotonic() >= request.deadline:
                        raise TimeoutError("Gateways did not prepare shutdown in time; no stop was committed")
                    await asyncio.sleep(_POLL_SECONDS)
            finally:
                # Atomic replacement may have succeeded even if its directory
                # fsync failed. Never overwrite an observable commit with abort.
                decision = _read_request(environment)
                if decision is not None and decision.attempt == request.attempt and decision.phase == "prepare":
                    write_record(_request_path(environment), request.model_copy(update={"phase": "abort"}).model_dump())

        # A receipt becomes inactive before its outer process/lease finishes.
        # Require actual process exit too, and leave lock acquisition to the
        # installer: neither an acknowledgement nor inventory grants that lock.
        deadline = time.monotonic() + timeout
        reviewed_runs = [item.receipt for item in plan.profiles]
        while True:
            try:
                require_stopped_profiles(plan.profiles, environment)
                runtime = GatewayRuntime()
                if all(not runtime.process_is_running(item.pid) or (
                    item.process_identity is not None
                    and runtime.process_identity_match(item.process_identity, item.pid) == "mismatch"
                ) for item in reviewed_runs):
                    completed = _read_request(environment)
                    if completed is not None and completed.plan_id == plan.id:
                        write_record(_request_path(environment), completed.model_copy(update={"phase": "stopped"}).model_dump())
                    return
            except ValueError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("Shutdown was committed but process exit is not confirmed; no package files were changed")
            await asyncio.sleep(_POLL_SECONDS)


def settle_uncommitted_handoff(directory: Path) -> JobStatus:
    """Retire a prepared/failed handoff without undoing a committed shutdown.

    The requesting gateway can remain running. No worker, orphan preflight or
    stop coordinator may still own the old job. Keep its files and confirmation
    for diagnosis; CANCELLED prevents a delayed launcher from using that consent.
    """
    spec = WorkerSpec.read(directory)
    root = installation_state_dir(spec.baseline.environment)
    with (file_access(root / "worker.lock", exclusive=True),
          file_access(root / "handoff-child.lock", exclusive=True),
          file_access(root / "stop.lock", exclusive=True),
          installation_access(environment=spec.baseline.environment)):
        status = JobStatus.read(directory)
        if status.mutation_started or status.phase not in {Phase.READY, Phase.HANDOFF_FAILED, Phase.CANCELLED}:
            raise ValueError("Only an unmodified, inactive handoff can be settled")
        request = _read_request(spec.baseline.environment)
        if request is not None and request.plan_id == spec.plan_id and request.phase in {"commit", "stopped"}:
            raise ValueError("Shutdown was committed; recover the saved update before starting another")
        if (directory / "approval.json").exists():
            raise ValueError("Installation was admitted; recover the saved update before starting another")
        if status.phase != Phase.CANCELLED:
            status = JobStatus(spec.plan_id, Phase.CANCELLED, status.attempt, False,
                               "Previous handoff settled; review a new plan before updating", int(time.time()))
            status.save(directory)
        return status
