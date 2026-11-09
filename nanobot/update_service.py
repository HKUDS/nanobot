"""Own exact-plan staging and execution consent independently of a client.

Staging does not grant installation consent. Each explicit execution confirmation
can launch its detached owner once; repeating an ID reads the durable record.
No phase automatically retries work. Clients do not own installer lifetimes.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path

from pydantic import Field, field_validator

from nanobot.installation_lock import (
    file_access,
    installation_access,
    installation_id,
    installation_state_dir,
    pending_update_path,
)
from nanobot.release_feed import ReleaseFeed
from nanobot.releases import ReleaseRecord
from nanobot.update_channel import (
    UpdateChannel,
    UpdateChannelRequest,
    read_update_channel,
    write_update_channel,
)
from nanobot.update_jobs import (
    UpdateJobNotFoundError,
    UpdateJobView,
    prepare_job,
    read_update_job,
    retry_handoff,
    settle_interrupted_preparation,
    start_handoff,
    validate_preparation,
)
from nanobot.update_plan import UpdatePlan, UpdatePlans
from nanobot.update_worker import JobStatus, Phase, read_record
from nanobot.utils.atomic_file import atomic_write_lines
from nanobot.utils.cancellation import shield_and_drain


class UpdateJobRequest(ReleaseRecord):
    id: str

    @field_validator("id")
    @classmethod
    def canonical_id(cls, value: str) -> str:
        return UpdatePlan.canonical_id(value)


class UpdateExecutionRequest(UpdateJobRequest):
    confirm_restart: bool

    @field_validator("confirm_restart")
    @classmethod
    def explicit_restart(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Confirm the reviewed shutdown and restart before updating")
        return value


class UpdateRetryRequest(UpdateExecutionRequest):
    previous_confirmation_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class UpdateJobService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._closing = False
        self._reapers: set[asyncio.Task[None]] = set()

    def has_pending_work(self) -> bool:
        return self._task is not None and not self._task.done()

    def change_channel(self, request: UpdateChannelRequest) -> UpdateChannel:
        """Change subscription only; retire inactive staged jobs, never rollback."""
        from nanobot.update_stop import settle_uncommitted_handoff

        root = installation_state_dir()
        with (file_access(root / "channel.lock", exclusive=True),
              file_access(root / "preparation-controller.lock", exclusive=True),
              installation_access(allow_incomplete=True)):
            current = read_update_channel()
            if request.revision != current.revision:
                raise ValueError("Update channel changed in another client; check again")
            if request.channel == current.channel:
                return current
            if self._closing or pending_update_path().exists():
                raise ValueError("Recover the current update before changing channels")
            staged: list[Path] = []
            for path in (root / "jobs").glob("*/status.json"):
                state = JobStatus.read(path.parent)
                if state.phase in {Phase.SUCCEEDED, Phase.RESTORED, Phase.CANCELLED, Phase.PREPARATION_FAILED}:
                    continue
                if state.phase not in {Phase.READY, Phase.HANDOFF_FAILED} or state.mutation_started:
                    raise ValueError("Finish or recover the current update before changing channels")
                staged.append(path.parent)
            # Existing settlement checks real worker leases, shutdown commit and
            # install admission. Changing preference cannot discard pending work.
            for directory in staged:
                settle_uncommitted_handoff(directory)
            selected = UpdateChannel(channel=request.channel, revision=current.revision + 1)
            write_update_channel(selected)
            return selected

    def prepare(self, plan_id: str) -> UpdateJobView:
        """Acknowledge one durable staging request; never install or restart."""
        if self._closing:
            raise RuntimeError("The update service is shutting down")
        loop = asyncio.get_running_loop()
        root = installation_state_dir()
        plan = UpdatePlans(root / "plans").load(plan_id)
        if plan.installation.installation_id != installation_id():
            raise ValueError("The plan belongs to another installation")
        try:
            return read_update_job(plan_id)
        except UpdateJobNotFoundError:
            pass
        # Acquire synchronously before acknowledging or starting a task. Another
        # profile may return this job's journal, but cannot start competing work.
        leases = ExitStack()
        try:
            leases.enter_context(file_access(root / "channel.lock", exclusive=False))
            leases.enter_context(file_access(root / "preparation-controller.lock", exclusive=True))
            leases.enter_context(installation_access())
            validate_preparation(plan)
            directory = root / "jobs" / plan_id
            if directory.is_symlink():
                raise ValueError("Invalid update job directory")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            plan_path = directory / "plan.json"
            if plan_path.exists():
                if UpdatePlan.model_validate(read_record(plan_path)) != plan:
                    raise ValueError("The job belongs to another plan")
            else:
                atomic_write_lines(plan_path, [plan.model_dump_json()])
                plan_path.chmod(0o600)
            # Recheck after taking the lease: a second process might have
            # finished between the first lookup and acquisition.
            if (directory / "status.json").exists():
                return read_update_job(plan_id)
            JobStatus(plan_id, Phase.PREPARATION_REQUESTED, 0, False,
                      "Preparation requested; no installation approved", int(time.time())).save(directory)
            result = read_update_job(plan_id)
            owned = leases.pop_all()
            self._task = loop.create_task(self._prepare(plan, owned), name="nanobot-update-prepare")
            # Also release if loop shutdown cancels before the coroutine enters.
            self._task.add_done_callback(lambda _: owned.close())
            return result
        finally:
            leases.close()

    async def _prepare(self, plan: UpdatePlan, leases: ExitStack) -> None:
        root = installation_state_dir()
        directory = root / "jobs" / plan.id
        with leases:
            try:
                async with ReleaseFeed(root / "releases") as feed:
                    # Revalidate the reviewed target, never resolve `latest`.
                    # prepare_job probes the actual environment under native
                    # child-owned leases before downloads or dependency work.
                    await feed.revalidate(plan.target)
                    await prepare_job(plan, feed)
            except (Exception, asyncio.CancelledError) as exc:
                # Raw errors can include private index URLs. Cancellation is
                # recorded only after prepare_job has settled native work.
                # A cancellation while closing the HTTP client cannot undo the
                # durable staging commit which prepare_job already completed.
                if not (directory / "request.json").exists():
                    JobStatus(plan.id, Phase.PREPARATION_FAILED, 0, False,
                              f"Preparation stopped ({type(exc).__name__}); no installation was started",
                              int(time.time())).save(directory)

    def settle(self, plan_id: str) -> UpdateJobView:
        """Settle inactive work before a new review; never retry or install."""
        job = read_update_job(plan_id)
        root = installation_state_dir()
        directory = root / "jobs" / plan_id
        with file_access(root / "preparation-controller.lock", exclusive=True):
            if job.recorded_phase == Phase.PREPARATION_REQUESTED:
                # No native child can start before PREPARING is persisted.
                with file_access(root / "prepare.lock", exclusive=True):
                    state = JobStatus.read(directory)
                    if state.phase != Phase.PREPARATION_REQUESTED or state.mutation_started or (directory / "request.json").exists():
                        raise ValueError("The preparation state changed")
                    JobStatus(plan_id, Phase.PREPARATION_FAILED, 0, False,
                              "Interrupted request settled; no installation was started", int(time.time())).save(directory)
            elif job.recorded_phase == Phase.PREPARING:
                settle_interrupted_preparation(directory)
            elif job.recorded_phase in {Phase.READY, Phase.HANDOFF_FAILED, Phase.CANCELLED}:
                from nanobot.update_stop import settle_uncommitted_handoff

                settle_uncommitted_handoff(directory)
            else:
                raise ValueError("Only an interrupted preparation or uncommitted handoff can be settled")
        return read_update_job(plan_id)

    async def execute(self, plan_id: str, *, previous_confirmation_id: str | None = None) -> UpdateJobView:
        """Confirm once, or explicitly retry the supplied previous confirmation.

        Repeating either request reads the durable result; it cannot launch twice.

        This handoff does not count itself as pending runtime work: its detached
        owner must be able to stop the requesting gateway. All unrelated work
        still participates in the cooperative idle-admission check.
        """
        if self._closing:
            raise RuntimeError("The update service is shutting down")
        job = read_update_job(plan_id)
        if previous_confirmation_id is not None:
            if job.execution_confirmation_id is None:
                raise ValueError("No execution confirmation is available to retry")
            if job.execution_confirmation_id != previous_confirmation_id:
                return job
        elif job.execution_confirmation_id is not None:
            return job
        directory = installation_state_dir() / "jobs" / plan_id
        plan = UpdatePlan.model_validate(read_record(directory / "plan.json"))
        if not plan.can_restart_inline:
            raise ValueError("Inline updates require reviewed shutdown and restart of this gateway and every running peer")
        loop = asyncio.get_running_loop()

        def launch() -> None:
            process = (start_handoff(directory, once=True) if previous_confirmation_id is None
                       else retry_handoff(directory, previous_confirmation_id))
            if process is not None:
                # Transfer the child even if cancellation means the HTTP caller
                # will never receive the thread's return value.
                loop.call_soon_threadsafe(self._track_worker, process)

        try:
            await shield_and_drain(asyncio.to_thread(launch))
        except (OSError, RuntimeError):
            # The launcher may have failed after persisting consent, or another
            # tab may already own the worker. Return durable facts, not a retry.
            latest = read_update_job(plan_id)
            if latest.execution_confirmation_id in {None, previous_confirmation_id}:
                raise
        return read_update_job(plan_id)

    def _track_worker(self, process: subprocess.Popen[bytes]) -> None:
        reaper = asyncio.create_task(self._reap(process), name="nanobot-update-reap")
        self._reapers.add(reaper)
        reaper.add_done_callback(self._reapers.discard)

    @staticmethod
    async def _reap(process: subprocess.Popen[bytes]) -> None:
        # Do not put process.wait in the default thread pool: gateway shutdown
        # would join that thread while this child is waiting for the gateway.
        while process.poll() is None:
            await asyncio.sleep(0.2)

    async def close(self) -> None:
        self._closing = True
        if self._task is not None:
            # Browser requests never own this task. Shutdown must also wait for
            # the real preparation, not release ownership on cancellation.
            while not self._task.done():
                try:
                    await asyncio.shield(self._task)
                except asyncio.CancelledError:
                    continue
            self._task.result()
        for reaper in self._reapers:
            reaper.cancel()
        await asyncio.gather(*self._reapers, return_exceptions=True)
