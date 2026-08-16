"""Gateway-specific configuration for the shared background process runtime."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from filelock import FileLock

from nanobot.config.paths import get_data_dir
from nanobot.process_runtime import (
    ManagedProcessRuntime,
    ProcessResult,
    ProcessRuntimePaths,
    ProcessStartOptions,
    ProcessStatus,
)

GatewayStartOptions = ProcessStartOptions
GatewayStatus = ProcessStatus
RuntimeResult = ProcessResult


def build_gateway_command(python_executable: str, options: GatewayStartOptions) -> list[str]:
    """Build a foreground gateway command for process supervisors."""
    command = [
        python_executable,
        "-m",
        "nanobot",
        "gateway",
        "--foreground",
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


@dataclass(frozen=True)
class GatewayRuntimePaths(ProcessRuntimePaths):
    """Filesystem layout for one gateway runtime instance."""

    @classmethod
    def for_instance(
        cls,
        *,
        data_dir: Path | None = None,
        workspace: str | None = None,
        config_path: str | None = None,
    ) -> "GatewayRuntimePaths":
        base = data_dir or get_data_dir()
        suffix = _instance_suffix(workspace=workspace, config_path=config_path)
        run_dir = base / "run"
        logs_dir = base / "logs"
        stem = "gateway" if suffix is None else f"gateway.{suffix}"
        return cls(
            run_dir=run_dir,
            logs_dir=logs_dir,
            state_path=run_dir / f"{stem}.json",
            log_path=logs_dir / f"{stem}.log",
        )


class GatewayRuntime(ManagedProcessRuntime[ProcessStartOptions]):
    """Manage a background ``nanobot gateway`` process."""

    service_name = "gateway"

    def __init__(
        self,
        *,
        paths: GatewayRuntimePaths | None = None,
        platform_name: str | None = None,
        python_executable: str | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        subprocess_run: Callable[..., Any] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(
            paths=paths or GatewayRuntimePaths.for_instance(),
            platform_name=platform_name,
            python_executable=python_executable,
            popen=popen,
            subprocess_run=subprocess_run,
            sleep=sleep,
        )

    def _build_child_command(self, options: ProcessStartOptions) -> list[str]:
        return build_gateway_command(self.python_executable, options)

    def restart(self, options: ProcessStartOptions, *, timeout_s: int = 20) -> ProcessResult:
        """Restart an existing gateway without creating a new persistent instance."""
        with self._lifecycle_lock():
            status = self.status()
            if not status.running:
                return ProcessResult(False, "gateway_not_running", status)
            stop_result = self._stop(timeout_s=timeout_s)
            if not stop_result.ok:
                return stop_result
            return self._start_background(options)


class GatewayClientLease:
    """Reference-count an on-demand gateway shared by local interactive clients."""

    def __init__(
        self,
        runtime: GatewayRuntime,
        *,
        kind: str,
        pid: int | None = None,
        token: str | None = None,
    ) -> None:
        self.runtime = runtime
        self.kind = kind
        self.pid = pid or os.getpid()
        self.token = token or uuid.uuid4().hex
        state_path = runtime.paths.state_path
        self.state_path = state_path.with_name(
            f"{state_path.stem}.clients{state_path.suffix}"
        )
        self.lock = FileLock(f"{self.state_path}.lock")
        self._acquired = False

    def acquire(self) -> None:
        """Register this client before it starts or attaches to the gateway."""
        with self.lock:
            state = self._live_state()
            clients = self._clients(state)
            clients[self.token] = {
                "pid": self.pid,
                "kind": self.kind,
            }
            self._write_state(state)
            self._acquired = True

    def mark_ephemeral(self) -> None:
        """Mark a gateway started by a client for last-client shutdown."""
        with self.lock:
            state = self._live_state()
            state["auto_stop"] = True
            self._write_state(state)

    def mark_persistent(self) -> bool:
        """Keep an explicitly backgrounded gateway alive; return whether it was promoted."""
        with self.lock:
            state = self._live_state()
            promoted = bool(state.get("auto_stop"))
            state["auto_stop"] = False
            self._write_or_clear(state)
            return promoted

    def clear(self) -> None:
        """Forget leases after an explicit gateway stop."""
        with self.lock:
            self.state_path.unlink(missing_ok=True)

    def release(self, *, timeout_s: int = 20) -> bool:
        """Release this client and stop an ephemeral gateway when it was the last."""
        if not self._acquired:
            return False
        with self.lock:
            state = self._live_state()
            clients = self._clients(state)
            clients.pop(self.token, None)
            self._acquired = False
            if clients or not bool(state.get("auto_stop")):
                self._write_or_clear(state)
                return False
            result = self.runtime.stop(timeout_s=timeout_s)
            stopped = result.ok or result.message == "gateway_not_running"
            if stopped:
                self.state_path.unlink(missing_ok=True)
            else:
                self._write_state(state)
            return stopped

    def _live_state(self) -> dict[str, object]:
        state = self._read_state()
        clients = self._clients(state)
        stale: list[str] = []
        for token, value in clients.items():
            if not isinstance(value, dict):
                stale.append(token)
                continue
            record = cast(dict[str, object], value)
            if not _pid_is_running(record.get("pid")):
                stale.append(token)
        for token in stale:
            clients.pop(token, None)
        return state

    @staticmethod
    def _clients(state: dict[str, object]) -> dict[str, object]:
        value = state.get("clients")
        if isinstance(value, dict):
            return cast(dict[str, object], value)
        clients: dict[str, object] = {}
        state["clients"] = clients
        return clients

    def _read_state(self) -> dict[str, object]:
        try:
            payload: object = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return {"auto_stop": False, "clients": {}}
        if isinstance(payload, dict):
            return cast(dict[str, object], payload)
        return {"auto_stop": False, "clients": {}}

    def _write_or_clear(self, state: dict[str, object]) -> None:
        clients = state.get("clients")
        if not clients and not bool(state.get("auto_stop")):
            self.state_path.unlink(missing_ok=True)
            return
        self._write_state(state)

    def _write_state(self, state: dict[str, object]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f"{self.state_path.name}.",
            suffix=".tmp",
            dir=self.state_path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.state_path)
        finally:
            temporary.unlink(missing_ok=True)


def _instance_suffix(*, workspace: str | None, config_path: str | None) -> str | None:
    raw = "|".join(value for value in (workspace, config_path) if value)
    if not raw:
        return None
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _pid_is_running(value: object) -> bool:
    if not isinstance(value, int) or value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
