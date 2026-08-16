"""Gateway-specific configuration for the shared background process runtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generator, Literal, cast

from filelock import FileLock

from nanobot.config.paths import get_data_dir
from nanobot.process_runtime import (
    ManagedProcessRuntime,
    ProcessResult,
    ProcessRuntimePaths,
    ProcessStartOptions,
    ProcessStatus,
    process_is_running,
)

GatewayStartOptions = ProcessStartOptions

GatewayLaunchMode = Literal["foreground", "background", "unknown"]
GatewayLifetime = Literal["explicit", "on_demand"]


@dataclass(frozen=True)
class GatewayStatus(ProcessStatus):
    """Observable lifecycle state for one shared local gateway."""

    launch_mode: GatewayLaunchMode = "unknown"
    lifetime: GatewayLifetime = "explicit"
    clients: int = 0


@dataclass(frozen=True)
class GatewayLeaseSnapshot:
    """Live local clients and the gateway lifetime they imply."""

    auto_stop: bool
    clients: int


@dataclass(frozen=True)
class RuntimeResult(ProcessResult):
    """Result of a gateway lifecycle operation."""

    status: GatewayStatus


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

    def start_background(self, options: ProcessStartOptions) -> RuntimeResult:
        """Start the gateway detached from the current terminal."""
        with self._lifecycle_lock():
            return self._start_background(options)

    def start_on_demand(self, options: ProcessStartOptions) -> RuntimeResult:
        """Atomically reuse a gateway or start one owned by local client leases."""
        with self._lifecycle_lock():
            status = self.status()
            if status.running:
                return RuntimeResult(False, "gateway_already_running", status)
            GatewayClientLease(self, kind="gateway-start").mark_ephemeral()
            return self._start_background(options)

    def _start_background(self, options: ProcessStartOptions) -> RuntimeResult:
        result = super()._start_background(options)
        if not result.ok:
            return self._result(result)
        state = self._read_state()
        if state and result.status.pid == state.get("pid"):
            state["launch_mode"] = "background"
            self._write_state(state)
        return RuntimeResult(True, result.message, self.status())

    def stop(self, *, timeout_s: int = 20) -> RuntimeResult:
        """Stop the gateway recorded by this runtime."""
        with self._lifecycle_lock():
            return self._result(self._stop(timeout_s=timeout_s))

    def status(self, *, reason: str | None = None) -> GatewayStatus:
        """Return process, launch, and client lifetime state in one snapshot."""
        process = super().status(reason=reason)
        state = self._read_state() if process.running else None
        raw_mode = state.get("launch_mode") if state else None
        launch_mode: GatewayLaunchMode = (
            raw_mode if raw_mode in {"foreground", "background"} else "unknown"
        )
        lease = GatewayClientLease(self, kind="gateway-status").snapshot()
        return GatewayStatus(
            running=process.running,
            pid=process.pid,
            state_path=process.state_path,
            log_path=process.log_path,
            started_at=process.started_at,
            port=process.port,
            command=process.command,
            reason=process.reason,
            launch_mode=launch_mode,
            lifetime="on_demand" if lease.auto_stop else "explicit",
            clients=lease.clients,
        )

    @contextmanager
    def foreground_instance(self, options: ProcessStartOptions) -> Generator[None]:
        """Publish this foreground gateway while it is available to local clients."""
        launch_mode = self._claim_current_process(options)
        if launch_mode == "foreground":
            GatewayClientLease(self, kind="gateway-foreground").mark_persistent()
        try:
            yield
        finally:
            self._release_current_process()

    def _claim_current_process(self, options: ProcessStartOptions) -> GatewayLaunchMode:
        with self._lifecycle_lock():
            state = self._read_state() or {}
            pid = os.getpid()
            launch_mode = (
                "background"
                if state.get("pid") == pid and state.get("launch_mode") == "background"
                else "foreground"
            )
            state.update(
                {
                    "pid": pid,
                    "identity": self._process_identity(pid),
                    "started_at": datetime.now(UTC).isoformat(),
                    "platform": self.platform_name,
                    "port": options.port,
                    "workspace": options.workspace,
                    "config_path": options.config_path,
                    "command": self._build_child_command(options),
                    "log_path": str(self.paths.log_path),
                    "launch_mode": launch_mode,
                }
            )
            self._write_state(state)
            return launch_mode

    def _release_current_process(self) -> None:
        with self._lifecycle_lock():
            state = self._read_state()
            if state and self._record_matches_process(state, os.getpid()):
                self._clear_state()

    def restart(self, options: ProcessStartOptions, *, timeout_s: int = 20) -> RuntimeResult:
        """Restart an existing gateway without creating a new persistent instance."""
        with self._lifecycle_lock():
            status = self.status()
            if not status.running:
                return RuntimeResult(False, "gateway_not_running", status)
            if status.launch_mode == "foreground":
                return RuntimeResult(False, "gateway_foreground_restart_required", status)
            stop_result = self._stop(timeout_s=timeout_s)
            if not stop_result.ok:
                return self._result(stop_result)
            return self._start_background(options)

    def _result(self, result: ProcessResult) -> RuntimeResult:
        status = result.status
        gateway_status = status if isinstance(status, GatewayStatus) else self.status()
        return RuntimeResult(result.ok, result.message, gateway_status)


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
                "identity": self._process_identity(self.pid),
            }
            self._write_state(state)
            self._acquired = True

    def ensure_on_demand_gateway(self, options: GatewayStartOptions) -> RuntimeResult:
        """Atomically reuse a gateway or start one owned by local client leases."""
        if not self._acquired:
            raise RuntimeError("gateway client lease must be acquired before startup")
        return self.runtime.start_on_demand(options)

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

    def snapshot(self) -> GatewayLeaseSnapshot:
        """Prune dead clients and return current lifetime state."""
        with self.lock:
            state = self._live_state()
            self._write_or_clear(state)
            return GatewayLeaseSnapshot(
                auto_stop=bool(state.get("auto_stop")),
                clients=len(self._clients(state)),
            )

    def orphaned_on_demand(self) -> bool:
        """Return whether an on-demand gateway has lost every live client."""
        snapshot = self.snapshot()
        return snapshot.auto_stop and snapshot.clients == 0

    def release(self, *, timeout_s: int = 20) -> bool:
        """Release this client and stop an ephemeral gateway when it was the last."""
        if not self._acquired:
            return False
        should_stop = False
        with self.lock:
            state = self._live_state()
            clients = self._clients(state)
            clients.pop(self.token, None)
            self._acquired = False
            should_stop = not clients and bool(state.get("auto_stop"))
            self._write_or_clear(state)
        if not should_stop:
            return False
        result = self.runtime.stop(timeout_s=timeout_s)
        with self.lock:
            stopped = result.ok or result.message == "gateway_not_running"
            if stopped:
                self.state_path.unlink(missing_ok=True)
            else:
                state = self._live_state()
                state["auto_stop"] = True
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
            pid = record.get("pid")
            identity = record.get("identity")
            if (
                not isinstance(pid, int)
                or not self._process_is_running(pid)
                or (identity is not None and identity != self._process_identity(pid))
            ):
                stale.append(token)
        for token in stale:
            clients.pop(token, None)
        return state

    def _process_identity(self, pid: int) -> str | int | None:
        resolver = getattr(self.runtime, "process_identity", None)
        value = resolver(pid) if callable(resolver) else None
        return value if isinstance(value, (str, int)) else None

    def _process_is_running(self, pid: int) -> bool:
        checker = getattr(self.runtime, "process_is_running", None)
        return bool(checker(pid)) if callable(checker) else process_is_running(pid)

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


async def monitor_gateway_clients(
    lease: GatewayClientLease,
    shutdown_event: asyncio.Event,
    *,
    poll_interval_s: float = 1.0,
) -> bool:
    """Stop waiting when an on-demand gateway loses every live client."""
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=poll_interval_s)
        except TimeoutError:
            if lease.orphaned_on_demand():
                shutdown_event.set()
                return True
    return False


def _instance_suffix(*, workspace: str | None, config_path: str | None) -> str | None:
    raw = "|".join(value for value in (workspace, config_path) if value)
    if not raw:
        return None
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
