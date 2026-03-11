"""POSIX managed daemon adapter for macOS rollout."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Callable

import typer

from nanobot.gateway_runtime.models import (
    GatewayStartOptions,
    GatewayStatus,
    RestartResult,
    RuntimeMode,
    RuntimePolicy,
    StartResult,
    StopResult,
)
from nanobot.gateway_runtime.state_store import GatewayStateStore


class PosixDaemonAdapter:
    """Start and control gateway as a detached child process on POSIX systems."""

    def __init__(
        self,
        *,
        policy: RuntimePolicy,
        state_store: GatewayStateStore | None = None,
        python_executable: str | None = None,
        popen_factory: Callable[..., object] = subprocess.Popen,
        time_module=time,
    ):
        self._policy = policy
        self._state_store = state_store or GatewayStateStore()
        self._python_executable = python_executable or sys.executable
        self._popen_factory = popen_factory
        self._time = time_module

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

        try:
            os.kill(pid, signal.SIGTERM)
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
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self._wait_for_exit(pid, 2)

        self._state_store.clear_pid()
        return StopResult(
            stopped=True,
            message="gateway_stopped_background_managed",
            mode=RuntimeMode.BACKGROUND_MANAGED,
        )

    def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
        self.stop(timeout_s=timeout_s)
        started = self.start(options)
        return RestartResult(
            restarted=started.started,
            message="gateway_restarted_background_managed"
            if started.started
            else "gateway_restart_failed",
            mode=RuntimeMode.BACKGROUND_MANAGED,
        )

    def status(self) -> GatewayStatus:
        state = self._state_store.read_state() or {}
        pid = self._state_store.read_pid()
        running = pid is not None and self._is_pid_running(pid)

        if not running:
            pid = None
            self._state_store.clear_pid()

        reason = state.get("reason", self._policy.reason)
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
            log_path=self._state_store.resolve_log_path(),
            started_at=started_at if isinstance(started_at, str) else None,
        )

    def logs(self, follow: bool = True, tail: int = 200) -> int:
        lines = self._state_store.read_log_tail(tail=tail)
        if not lines:
            typer.echo("No gateway log output available yet.")
            if not follow:
                return 0
        else:
            for line in lines:
                typer.echo(line)

        if not follow:
            return 0

        log_path = self._state_store.resolve_log_path()
        log_path.touch(exist_ok=True)
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(0, os.SEEK_END)
                while True:
                    line = handle.readline()
                    if line:
                        typer.echo(line.rstrip("\n"))
                        continue
                    self._time.sleep(0.5)
        except KeyboardInterrupt:
            return 130

    def _cleanup_failed_start(self, pid: int) -> None:
        self._state_store.clear_pid()

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

        if self._wait_for_exit(pid, 2):
            return

        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    def _wait_for_stable_start(self, pid: int, timeout_s: float) -> bool:
        deadline = self._time.monotonic() + max(timeout_s, 0.0)
        while self._time.monotonic() < deadline:
            if not self._is_pid_running(pid):
                return False
            self._time.sleep(0.1)
        return self._is_pid_running(pid)

    def _build_child_command(self, options: GatewayStartOptions) -> list[str]:
        command = [
            self._python_executable,
            "-m",
            "nanobot",
            "gateway",
            "--foreground",
            "--runtime-child",
            "--port",
            str(options.port),
        ]
        if options.verbose:
            command.append("--verbose")
        if options.workspace:
            command.extend(["--workspace", options.workspace])
        if options.config_path:
            command.extend(["--config", options.config_path])
        return command

    def _wait_for_exit(self, pid: int, timeout_s: int) -> bool:
        deadline = self._time.monotonic() + max(timeout_s, 0)
        while self._time.monotonic() < deadline:
            if not self._is_pid_running(pid):
                return True
            self._time.sleep(0.1)
        return not self._is_pid_running(pid)

    def _is_pid_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
