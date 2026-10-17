"""Background process control for the WebUI-managed OpenAI-compatible API."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Generator

from nanobot.process_runtime import (
    ManagedProcessRuntime,
    ProcessResult,
    ProcessRuntimePaths,
    ProcessStartOptions,
)


@dataclass(frozen=True)
class ApiStartOptions(ProcessStartOptions):
    """Options needed to start a managed ``nanobot serve`` process."""

    host: str = "127.0.0.1"


def api_runtime_paths(home: Path) -> ProcessRuntimePaths:
    """Return the API process state and log paths for one home."""
    resolved = home.expanduser().resolve(strict=False)
    run_dir = resolved / "run"
    logs_dir = resolved / "logs"
    return ProcessRuntimePaths(
        run_dir=run_dir,
        logs_dir=logs_dir,
        state_path=run_dir / "api.json",
        log_path=logs_dir / "api.log",
    )


class ApiRuntime(ManagedProcessRuntime[ApiStartOptions]):
    """Manage a WebUI-controlled OpenAI-compatible API process."""

    service_name = "api"

    @contextmanager
    def foreground_instance(self, options: ApiStartOptions) -> Generator[None]:
        """Claim the home API component while a foreground server runs."""
        pid = os.getpid()
        with self._lifecycle_lock():
            current = self.status()
            if current.running and self.selectors_mismatch(current, options):
                raise RuntimeError("api_instance_mismatch")
            current_state = self._read_state() or {}
            pid_handoff = self._pending_parent_pid_handoff(current, current_state)
            if current.running and current.pid != pid and not pid_handoff:
                raise RuntimeError("api_already_running")
            launch_mode = (
                "background"
                if current.running
                and current_state.get("launch_mode") == "background"
                else "foreground"
            )
            state: dict[str, object] = {
                "pid": pid,
                "started_at": datetime.now(UTC).isoformat(),
                "platform": self.platform_name,
                "port": options.port,
                "workspace": options.workspace,
                "config_path": options.config_path,
                "home": options.home,
                "command": self._build_child_command(options),
                "log_path": str(self.paths.log_path),
                "launch_mode": launch_mode,
            }
            state.update(self.process_identity_record(pid))
            self._write_state(state)
        try:
            yield
        finally:
            with self._lifecycle_lock():
                record = self._read_state()
                if record and self._record_matches_process(record, pid):
                    self._clear_state()

    def restart(self, options: ApiStartOptions, *, timeout_s: int = 20) -> ProcessResult:
        """Restart a managed API without replacing an attached foreground server."""
        with self._lifecycle_lock():
            current = self.status()
            if current.running and self.selectors_mismatch(current, options):
                return ProcessResult(False, "api_instance_mismatch", current)
            state = self._read_state()
            if current.running and state and state.get("launch_mode") == "foreground":
                return ProcessResult(False, "api_foreground_restart_required", current)
            stopped = self._stop(timeout_s=timeout_s)
            if not stopped.ok and stopped.message not in {
                "api_not_running", "api_state_stale",
            }:
                return stopped
            return self._start_background(options)

    def _build_child_command(self, options: ApiStartOptions) -> list[str]:
        command = [
            self.python_executable or sys.executable,
            "-m",
            "nanobot",
        ]
        if options.home:
            command.extend(["--home", options.home])
        command.extend(["serve", "--host", options.host, "--port", str(options.port)])
        if options.verbose:
            command.append("--verbose")
        if options.workspace:
            command.extend(["--workspace", options.workspace])
        if options.config_path:
            command.extend(["--config", options.config_path])
        return command
