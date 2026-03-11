"""Windows managed daemon adapter with process-group aware termination."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Callable

import typer

from nanobot.gateway_runtime.models import (
    GatewayStartOptions,
    GatewayStatus,
    RestartResult,
    RuntimeMode,
    StartResult,
    StopResult,
)
from nanobot.gateway_runtime.state_store import GatewayStateStore

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
ERROR_ACCESS_DENIED = 5


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class WindowsDaemonAdapter:
    """Windows background adapter using process groups and taskkill fallback."""

    def __init__(
        self,
        *,
        policy,
        state_store: GatewayStateStore | None = None,
        python_executable: str | None = None,
        popen_factory: Callable[..., object] = subprocess.Popen,
        subprocess_run: Callable[..., object] = subprocess.run,
        time_module=time,
        create_new_process_group: int | None = None,
        create_no_window: int | None = None,
        ctrl_break_event: int | None = None,
        kernel32=None,
    ):
        self._policy = policy
        self._state_store = state_store or GatewayStateStore()
        self._python_executable = python_executable or sys.executable
        self._popen_factory = popen_factory
        self._subprocess_run = subprocess_run
        self._time = time_module
        self._create_new_process_group = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            if create_new_process_group is None and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
            else (create_new_process_group or 0)
        )
        self._create_no_window = (
            subprocess.CREATE_NO_WINDOW
            if create_no_window is None and hasattr(subprocess, "CREATE_NO_WINDOW")
            else (create_no_window or 0)
        )
        self._ctrl_break_event = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break_event is not None:
            self._ctrl_break_event = ctrl_break_event
        self._kernel32 = kernel32
        self._kernel32_configured = False

    def start(self, options: GatewayStartOptions) -> StartResult:
        command = self._build_child_command(options)
        log_path = self._state_store.resolve_log_path()
        creationflags = self._create_new_process_group

        with log_path.open("a", encoding="utf-8") as log_handle:
            process = self._popen_factory(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )

        pid = int(process.pid)  # type: ignore[attr-defined]
        if not self._wait_for_stable_start(pid, timeout_s=0.5):
            self._cleanup_failed_start(pid)
            raise RuntimeError("background_process_exited_during_startup")

        process_identity = self._get_process_identity(pid)
        if process_identity is None:
            self._cleanup_failed_start(pid)
            raise RuntimeError("background_process_identity_unavailable")

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
                    "process_identity": process_identity,
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

        running = self._probe_pid_running(pid)
        if running is False:
            self._state_store.clear_pid()
            self._write_state_update(state, last_stop_method="already_stopped")
            return StopResult(
                stopped=True,
                message="background_process_already_stopped",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )
        if running is None:
            self._write_state_update(state, last_stop_method="status_unknown_access_denied")
            return StopResult(
                stopped=False,
                message="background_process_status_unknown",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        identity_valid = self._validate_process_identity(state, pid)
        if identity_valid is False:
            self._state_store.clear_pid()
            self._write_state_update(state, last_stop_method="identity_mismatch")
            return StopResult(
                stopped=False,
                message="background_process_identity_mismatch",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )
        if identity_valid is None:
            self._write_state_update(state, last_stop_method="identity_unknown_access_denied")
            return StopResult(
                stopped=False,
                message="background_process_status_unknown",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        if self._ctrl_break_event is not None:
            try:
                os.kill(pid, self._ctrl_break_event)
            except OSError:
                pass
            if self._wait_for_exit(pid, timeout_s):
                self._state_store.clear_pid()
                self._write_state_update(state, last_stop_method="ctrl_break_event")
                return StopResult(
                    stopped=True,
                    message="gateway_stopped_background_managed",
                    mode=RuntimeMode.BACKGROUND_MANAGED,
                )

        self._run_subprocess(["taskkill", "/PID", str(pid), "/T"])
        if self._wait_for_exit(pid, 2):
            self._state_store.clear_pid()
            self._write_state_update(state, last_stop_method="taskkill_tree")
            return StopResult(
                stopped=True,
                message="gateway_stopped_background_managed",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        self._run_subprocess(["taskkill", "/PID", str(pid), "/T", "/F"])
        self._wait_for_exit(pid, 2)
        self._state_store.clear_pid()
        self._write_state_update(state, last_stop_method="taskkill_tree_force")
        return StopResult(
            stopped=True,
            message="gateway_stopped_background_managed",
            mode=RuntimeMode.BACKGROUND_MANAGED,
        )

    def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
        stop_result = self.stop(timeout_s=timeout_s)
        if not stop_result.stopped and stop_result.message != "background_process_not_found":
            return RestartResult(
                restarted=False,
                message=stop_result.message,
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )
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
        if pid is None:
            return GatewayStatus(
                running=False,
                mode=RuntimeMode.BACKGROUND_MANAGED,
                reason=str(state.get("reason", self._policy.reason)),
                platform=str(state.get("platform", self._policy.platform)),
                rollout_stage=str(state.get("rollout_stage", self._policy.rollout_stage)),
                pid=None,
                log_path=self._state_store.resolve_log_path(),
                started_at=None,
            )

        running = self._probe_pid_running(pid)
        if running is False:
            self._state_store.clear_pid()
            return GatewayStatus(
                running=False,
                mode=RuntimeMode.BACKGROUND_MANAGED,
                reason="stale_pid_not_running",
                platform=str(state.get("platform", self._policy.platform)),
                rollout_stage=str(state.get("rollout_stage", self._policy.rollout_stage)),
                pid=None,
                log_path=self._state_store.resolve_log_path(),
                started_at=None,
            )
        if running is None:
            return GatewayStatus(
                running=False,
                mode=RuntimeMode.BACKGROUND_MANAGED,
                reason="process_status_unknown_access_denied",
                platform=str(state.get("platform", self._policy.platform)),
                rollout_stage=str(state.get("rollout_stage", self._policy.rollout_stage)),
                pid=pid,
                log_path=self._state_store.resolve_log_path(),
                started_at=state.get("started_at") if isinstance(state.get("started_at"), str) else None,
            )

        identity_valid = self._validate_process_identity(state, pid)
        if identity_valid is False:
            self._state_store.clear_pid()
            return GatewayStatus(
                running=False,
                mode=RuntimeMode.BACKGROUND_MANAGED,
                reason="stale_pid_identity_mismatch",
                platform=str(state.get("platform", self._policy.platform)),
                rollout_stage=str(state.get("rollout_stage", self._policy.rollout_stage)),
                pid=None,
                log_path=self._state_store.resolve_log_path(),
                started_at=None,
            )
        if identity_valid is None:
            return GatewayStatus(
                running=False,
                mode=RuntimeMode.BACKGROUND_MANAGED,
                reason="process_status_unknown_access_denied",
                platform=str(state.get("platform", self._policy.platform)),
                rollout_stage=str(state.get("rollout_stage", self._policy.rollout_stage)),
                pid=pid,
                log_path=self._state_store.resolve_log_path(),
                started_at=state.get("started_at") if isinstance(state.get("started_at"), str) else None,
            )

        return GatewayStatus(
            running=True,
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason=str(state.get("reason", self._policy.reason)),
            platform=str(state.get("platform", self._policy.platform)),
            rollout_stage=str(state.get("rollout_stage", self._policy.rollout_stage)),
            pid=pid,
            log_path=self._state_store.resolve_log_path(),
            started_at=state.get("started_at") if isinstance(state.get("started_at"), str) else None,
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

    def _write_state_update(self, state: dict[str, object], **updates: object) -> None:
        payload = dict(state)
        payload.update(updates)
        if "mode" not in payload:
            payload["mode"] = RuntimeMode.BACKGROUND_MANAGED.value
        if "platform" not in payload:
            payload["platform"] = self._policy.platform
        if "rollout_stage" not in payload:
            payload["rollout_stage"] = self._policy.rollout_stage
        if "reason" not in payload:
            payload["reason"] = self._policy.reason
        self._state_store.write_state(payload)

    def _validate_process_identity(self, state: dict[str, object], pid: int) -> bool | None:
        recorded_identity = state.get("process_identity")
        if not isinstance(recorded_identity, str) or not recorded_identity:
            return False
        current_identity, error = self._read_process_identity(pid)
        if current_identity is None:
            if error == ERROR_ACCESS_DENIED:
                return None
            return False
        return current_identity == recorded_identity

    def _run_subprocess(self, cmd: list[str]) -> None:
        self._subprocess_run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def _cleanup_failed_start(self, pid: int) -> None:
        self._state_store.clear_pid()
        try:
            if self._ctrl_break_event is not None:
                os.kill(pid, self._ctrl_break_event)
        except OSError:
            return
        if self._wait_for_exit(pid, 2):
            return
        self._run_subprocess(["taskkill", "/PID", str(pid), "/T", "/F"])

    def _wait_for_stable_start(self, pid: int, timeout_s: float) -> bool:
        deadline = self._time.monotonic() + max(timeout_s, 0.0)
        while self._time.monotonic() < deadline:
            if self._is_pid_running(pid) is False:
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
            if self._is_pid_running(pid) is False:
                return True
            self._time.sleep(0.1)
        return self._is_pid_running(pid) is False

    def _get_kernel32(self):
        if self._kernel32 is None:
            self._kernel32 = ctypes.windll.kernel32
        if not self._kernel32_configured:
            self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self._kernel32.OpenProcess.restype = wintypes.HANDLE
            self._kernel32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(_FILETIME),
                ctypes.POINTER(_FILETIME),
                ctypes.POINTER(_FILETIME),
                ctypes.POINTER(_FILETIME),
            ]
            self._kernel32.GetProcessTimes.restype = wintypes.BOOL
            self._kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            self._kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            self._kernel32.CloseHandle.restype = wintypes.BOOL
            self._kernel32.GetLastError.argtypes = []
            self._kernel32.GetLastError.restype = wintypes.DWORD
            self._kernel32_configured = True
        return self._kernel32

    def _open_process(self, pid: int) -> tuple[object | None, int | None]:
        kernel32 = self._get_kernel32()
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None, int(kernel32.GetLastError())
        return handle, None

    def _read_process_identity(self, pid: int) -> tuple[str | None, int | None]:
        kernel32 = self._get_kernel32()
        handle, error = self._open_process(pid)
        if handle is None:
            return None, error
        try:
            creation_time = _FILETIME()
            exit_time = _FILETIME()
            kernel_time = _FILETIME()
            user_time = _FILETIME()
            ok = kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation_time),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            )
            if not ok:
                return None, int(kernel32.GetLastError())
            value = (creation_time.dwHighDateTime << 32) | creation_time.dwLowDateTime
            return str(value), None
        finally:
            kernel32.CloseHandle(handle)

    def _get_process_identity(self, pid: int) -> str | None:
        identity, _error = self._read_process_identity(pid)
        return identity

    def _probe_pid_running(self, pid: int) -> bool | None:
        kernel32 = self._get_kernel32()
        handle, error = self._open_process(pid)
        if handle is None:
            if error == ERROR_ACCESS_DENIED:
                return None
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                error = int(kernel32.GetLastError())
                if error == ERROR_ACCESS_DENIED:
                    return None
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    def _is_pid_running(self, pid: int) -> bool:
        probe = self._probe_pid_running(pid)
        return probe is not False



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
