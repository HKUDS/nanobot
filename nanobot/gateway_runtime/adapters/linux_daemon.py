"""Linux managed daemon adapter with session and process-group control."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Callable

from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter
from nanobot.gateway_runtime.models import (
    GatewayStartOptions,
    GatewayStatus,
    RuntimeMode,
    StartResult,
    StopResult,
)


class LinuxDaemonAdapter(PosixDaemonAdapter):
    """Linux daemon adapter with process-group aware stop semantics."""

    def __init__(
        self,
        *,
        policy,
        state_store=None,
        python_executable: str | None = None,
        popen_factory: Callable[..., object] = subprocess.Popen,
        time_module=time,
    ):
        super().__init__(
            policy=policy,
            state_store=state_store,
            python_executable=python_executable,
            popen_factory=popen_factory,
            time_module=time_module,
        )

    def start(self, options: GatewayStartOptions) -> StartResult:
        command = self._build_child_command(options)
        log_path = self._state_store.resolve_log_path()

        with log_path.open("a", encoding="utf-8") as log_handle:
            process = self._popen_factory(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        pid = int(process.pid)  # type: ignore[attr-defined]
        if not self._wait_for_stable_start(pid, timeout_s=0.5):
            self._cleanup_failed_start(pid)
            raise RuntimeError("background_process_exited_during_startup")

        pgid = self._resolve_process_group_id(pid)
        started_at = _utc_now()
        try:
            self._state_store.write_pid(pid)
            self._state_store.write_state(
                {
                    "mode": RuntimeMode.BACKGROUND_MANAGED.value,
                    "reason": self._policy.reason,
                    "platform": self._policy.platform,
                    "rollout_stage": self._policy.rollout_stage,
                    "pid": pid,
                    "pgid": pgid,
                    "started_at": started_at,
                    "log_path": str(log_path),
                }
            )
        except Exception:
            self._cleanup_failed_start(pid)
            raise
        return StartResult(
            started=True,
            message="gateway_started_background_managed",
            mode=RuntimeMode.BACKGROUND_MANAGED,
        )

    def stop(self, timeout_s: int = 20) -> StopResult:
        state = self._state_store.read_state() or {}
        pid = self._state_store.read_pid()
        if pid is None:
            return StopResult(
                stopped=False,
                message="background_process_not_found",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        if not self._is_pid_running(pid):
            self._state_store.clear_pid()
            return StopResult(
                stopped=True,
                message="background_process_already_stopped",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        pgid = self._extract_pgid(state, pid)
        try:
            self._signal_process(pgid=pgid, pid=pid, sig=signal.SIGTERM)
        except ProcessLookupError:
            self._state_store.clear_pid()
            return StopResult(
                stopped=True,
                message="background_process_already_stopped",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        terminated = self._wait_for_exit(pid, timeout_s)
        if not terminated:
            try:
                self._signal_process(pgid=pgid, pid=pid, sig=signal.SIGKILL)
            except ProcessLookupError:
                pass
            self._wait_for_exit(pid, 2)

        self._state_store.clear_pid()
        return StopResult(
            stopped=True,
            message="gateway_stopped_background_managed",
            mode=RuntimeMode.BACKGROUND_MANAGED,
        )

    def status(self) -> GatewayStatus:
        state = self._state_store.read_state() or {}
        pid = self._state_store.read_pid()
        running = pid is not None and self._is_pid_running(pid)

        if not running:
            stale_pid = pid is not None
            pid = None
            self._state_store.clear_pid()
            reason = "stale_pid_not_running" if stale_pid else state.get("reason", self._policy.reason)
            pgid = None
        else:
            reason = state.get("reason", self._policy.reason)
            pgid = self._extract_pgid(state, pid)

        platform = state.get("platform", self._policy.platform)
        rollout_stage = state.get("rollout_stage", self._policy.rollout_stage)
        started_at = state.get("started_at")

        return GatewayStatus(
            running=running,
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason=str(reason),
            platform=str(platform),
            rollout_stage=str(rollout_stage),
            pid=pid,
            pgid=pgid,
            log_path=self._state_store.resolve_log_path(),
            started_at=started_at if isinstance(started_at, str) else None,
        )

    def _cleanup_failed_start(self, pid: int) -> None:
        self._state_store.clear_pid()
        pgid = self._resolve_process_group_id(pid)

        try:
            self._signal_process(pgid=pgid, pid=pid, sig=signal.SIGTERM)
        except OSError:
            return

        if self._wait_for_exit(pid, 2):
            return

        try:
            self._signal_process(pgid=pgid, pid=pid, sig=signal.SIGKILL)
        except OSError:
            pass

    def _extract_pgid(self, state: dict[str, object], pid: int) -> int | None:
        raw_pgid = state.get("pgid")
        if isinstance(raw_pgid, int):
            return raw_pgid
        return self._resolve_process_group_id(pid)

    def _resolve_process_group_id(self, pid: int) -> int | None:
        try:
            return os.getpgid(pid)
        except OSError:
            return None

    def _signal_process(self, *, pgid: int | None, pid: int, sig: int) -> None:
        if pgid is not None:
            try:
                os.killpg(pgid, sig)
                return
            except OSError:
                pass
        os.kill(pid, sig)



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
