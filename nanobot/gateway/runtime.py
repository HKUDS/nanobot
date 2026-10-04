"""Gateway-specific configuration for the shared background process runtime."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import hashlib
import http.client
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
    process_identity_record,
    process_is_running,
)

GatewayStartOptions = ProcessStartOptions

GatewayLaunchMode = Literal["foreground", "background", "unknown"]
GatewayLifetime = Literal["explicit", "on_demand"]


def _gateway_health_ready(host: str, port: int, *, timeout_s: float = 0.4) -> bool:
    """Read readiness from the management listener without using proxy settings."""
    connect_host = "127.0.0.1" if host in {"", "0.0.0.0"} else "::1" if host == "::" else host
    connection = http.client.HTTPConnection(connect_host, port, timeout=timeout_s)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        body = response.read(1024)
    except (OSError, http.client.HTTPException, TimeoutError):
        return False
    finally:
        connection.close()
    if response.status != 200:
        return False
    try:
        raw_payload = cast(object, json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(raw_payload, dict):
        return False
    payload = cast(dict[str, object], raw_payload)
    return (
        payload.get("status") == "ok"
        and payload.get("ready") is not False
    )


def _default_config_path() -> Path:
    return (Path.home() / ".nanobot" / "config.json").resolve(strict=False)


@dataclass(frozen=True)
class GatewayStatus(ProcessStatus):
    """Observable lifecycle state for one shared local gateway."""

    launch_mode: GatewayLaunchMode = "unknown"
    lifetime: GatewayLifetime = "explicit"
    clients: int = 0
    ready: bool | None = None


@dataclass(frozen=True)
class GatewayLeaseSnapshot:
    """Live local clients and the gateway lifetime they imply."""

    auto_stop: bool
    clients: int


@dataclass(frozen=True)
class RuntimeResult(ProcessResult):
    """Result of a gateway lifecycle operation."""

    status: GatewayStatus
    promoted: bool = False


class GatewayAlreadyRunningError(RuntimeError):
    """Raised when a foreground gateway tries to replace a live instance."""

    def __init__(self, status: GatewayStatus) -> None:
        super().__init__("gateway_already_running")
        self.status = status


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


@dataclass(frozen=True)
class GatewayInstance:
    """One stable local gateway identity and its child-process selectors."""

    config_path: Path
    workspace: str | None
    paths: GatewayRuntimePaths

    @classmethod
    def resolve(
        cls,
        *,
        config_path: str | Path,
        workspace: str | None = None,
    ) -> "GatewayInstance":
        resolved_config = Path(config_path).expanduser().resolve(strict=False)
        resolved_workspace = (
            str(Path(workspace).expanduser().resolve(strict=False)) if workspace else None
        )
        # The released default instance used gateway.json. Keep that identity stable
        # across upgrades while still namespacing explicit configs and workspaces.
        config_selector = (
            None if resolved_config == _default_config_path() else str(resolved_config)
        )
        return cls(
            config_path=resolved_config,
            workspace=resolved_workspace,
            paths=GatewayRuntimePaths.for_instance(
                data_dir=resolved_config.parent,
                workspace=resolved_workspace,
                config_path=config_selector,
            ),
        )

    def start_options(
        self,
        *,
        port: int,
        verbose: bool = False,
    ) -> GatewayStartOptions:
        return GatewayStartOptions(
            port=port,
            verbose=verbose,
            workspace=self.workspace,
            config_path=(
                None if self.config_path == _default_config_path() else str(self.config_path)
            ),
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

    def _transition_lock(self) -> FileLock:
        """Serialize long lifecycle transitions without blocking child cleanup."""
        return FileLock(f"{self.paths.state_path}.transition.lock")

    def start_background(self, options: ProcessStartOptions) -> RuntimeResult:
        """Start the gateway detached from the current terminal."""
        lease = GatewayClientLease(self, kind="gateway-background")
        while True:
            lease.wait_for_shutdown()
            with self._transition_lock(), self._lifecycle_lock():
                promoted = lease._try_mark_persistent_locked()
                if promoted is None:
                    continue
                result = self._start_background(options)
                return RuntimeResult(result.ok, result.message, result.status, promoted)

    def start_on_demand(self, options: ProcessStartOptions) -> RuntimeResult:
        """Atomically reuse a gateway or start one owned by local client leases."""
        lease = GatewayClientLease(self, kind="gateway-start")
        while True:
            lease.wait_for_shutdown()
            with self._transition_lock(), self._lifecycle_lock():
                if lease._shutdown_pending_locked():
                    continue
                status = self.status()
                if status.running:
                    return RuntimeResult(False, "gateway_already_running", status)
                lease._mark_ephemeral_locked()
                return self._start_background(options)

    def _start_background(self, options: ProcessStartOptions) -> RuntimeResult:
        result = super()._start_background(options)
        if not result.ok:
            return self._result(result)
        state = self._read_state()
        if state and result.status.pid == state.get("pid"):
            state["launch_mode"] = "background"
            state["pending_pid_handoff"] = True
            self._write_state(state)
        return RuntimeResult(True, result.message, self.status())

    def stop(self, *, timeout_s: int = 20) -> RuntimeResult:
        """Stop the gateway recorded by this runtime."""
        with self._transition_lock():
            result = self._stop(timeout_s=timeout_s)
            with self._lifecycle_lock():
                if result.ok or result.message in {
                    "gateway_not_running",
                    "gateway_state_stale",
                }:
                    GatewayClientLease(self, kind="gateway-stop")._clear_locked()
            return self._result(result)

    def status(self, *, reason: str | None = None) -> GatewayStatus:
        """Return process, launch, and client lifetime state in one snapshot."""
        process = super().status(reason=reason)
        state = self._read_state() if process.running else None
        raw_mode = state.get("launch_mode") if state else None
        launch_mode: GatewayLaunchMode = (
            raw_mode if raw_mode in {"foreground", "background"} else "unknown"
        )
        lease = GatewayClientLease(self, kind="gateway-status").snapshot()
        ready: bool | None = None
        health_host = state.get("health_host") if state else None
        if (
            process.running
            and process.pid != os.getpid()
            and isinstance(health_host, str)
            and process.port is not None
        ):
            ready = _gateway_health_ready(health_host, process.port)
        status_reason = process.reason
        if ready is False and reason is None and status_reason == "running":
            status_reason = "websocket_unavailable"
        return GatewayStatus(
            running=process.running,
            pid=process.pid,
            state_path=process.state_path,
            log_path=process.log_path,
            started_at=process.started_at,
            port=process.port,
            command=process.command,
            reason=status_reason,
            launch_mode=launch_mode,
            lifetime="on_demand" if lease.auto_stop else "explicit",
            clients=lease.clients,
            ready=ready,
        )

    def publish_health_host(self, host: str) -> None:
        """Record the management bind host for out-of-process readiness diagnostics."""
        with self._lifecycle_lock():
            state = self._read_state()
            if not state or not self._record_matches_process(state, os.getpid()):
                return
            state["health_host"] = host
            self._write_state(state)

    @contextmanager
    def foreground_instance(self, options: ProcessStartOptions) -> Generator[None]:
        """Publish this foreground gateway while it is available to local clients."""
        self._claim_current_process(options)
        try:
            yield
        finally:
            self._release_current_process()

    def _claim_current_process(self, options: ProcessStartOptions) -> GatewayLaunchMode:
        lease = GatewayClientLease(self, kind="gateway-foreground")
        pid = os.getpid()
        while True:
            lease.wait_for_shutdown()
            with self._transition_lock(), self._lifecycle_lock():
                current = self.status()
                state = self._read_state() or {}
                pid_handoff = (
                    self.platform_name == "Windows"
                    and current.running
                    and current.pid != pid
                    and current.pid == os.getppid()
                    and state.get("pid") == current.pid
                    and state.get("launch_mode") == "background"
                    and state.get("pending_pid_handoff") is True
                )
                if current.running and current.pid != pid and not pid_handoff:
                    raise GatewayAlreadyRunningError(current)
                if lease._shutdown_pending_locked():
                    continue
                launch_mode: GatewayLaunchMode = (
                    "background"
                    if state.get("launch_mode") == "background"
                    and (state.get("pid") == pid or pid_handoff)
                    else "foreground"
                )
                state.update(
                    {
                        "pid": pid,
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
                state.pop("pending_pid_handoff", None)
                state.pop("stable_identity", None)
                state.update(self.process_identity_record(pid))
                self._write_state(state)
                if launch_mode == "foreground":
                    lease._try_mark_persistent_locked()
                return launch_mode

    def _release_current_process(self) -> None:
        with self._lifecycle_lock():
            state = self._read_state()
            if state and self._record_matches_process(state, os.getpid()):
                self._clear_state()
            GatewayClientLease(
                self,
                kind="gateway-exit",
            )._finish_shutdown_locked()

    def restart(self, options: ProcessStartOptions, *, timeout_s: int = 20) -> RuntimeResult:
        """Restart an existing gateway without creating a new persistent instance."""
        with self._transition_lock():
            with self._lifecycle_lock():
                status = self.status()
                if not status.running:
                    return RuntimeResult(False, "gateway_not_running", status)
                if status.launch_mode == "foreground":
                    return RuntimeResult(
                        False,
                        "gateway_foreground_restart_required",
                        status,
                    )
            stop_result = self._stop(timeout_s=timeout_s)
            if not stop_result.ok:
                return self._result(stop_result)
            with self._lifecycle_lock():
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
        self.transition_lock = FileLock(f"{state_path}.transition.lock")
        self.lifecycle_lock = FileLock(f"{state_path}.lock")
        self.lock = FileLock(f"{self.state_path}.lock")
        self._acquired = False

    def acquire(self) -> None:
        """Register this client before it starts or attaches to the gateway."""
        while True:
            self.wait_for_shutdown()
            with self.transition_lock, self.lifecycle_lock, self.lock:
                state = self._live_state()
                if state.get("stopping"):
                    continue
                self._register(state)
                return

    def ensure_on_demand_gateway(self, options: GatewayStartOptions) -> RuntimeResult:
        """Atomically reuse a gateway or start one owned by local client leases."""
        if not self._acquired:
            raise RuntimeError("gateway client lease must be acquired before startup")
        return self.runtime.start_on_demand(options)

    def mark_ephemeral(self) -> None:
        """Mark a gateway started by a client for last-client shutdown."""
        with self.transition_lock, self.lifecycle_lock:
            self._mark_ephemeral_locked()

    def _mark_ephemeral_locked(self) -> None:
        with self.lock:
            state = self._live_state()
            state["auto_stop"] = True
            self._write_state(state)

    def mark_persistent(self) -> bool:
        """Keep an explicitly backgrounded gateway alive; return whether it was promoted."""
        while True:
            self.wait_for_shutdown()
            with self.transition_lock, self.lifecycle_lock:
                promoted = self._try_mark_persistent_locked()
                if promoted is not None:
                    return promoted

    def _try_mark_persistent_locked(self) -> bool | None:
        with self.lock:
            state = self._live_state()
            if state.get("stopping"):
                return None
            promoted = bool(state.get("auto_stop"))
            state["auto_stop"] = False
            self._write_or_clear(state)
            return promoted

    def clear(self) -> None:
        """Forget leases after an explicit gateway stop."""
        with self.transition_lock, self.lifecycle_lock:
            self._clear_locked()

    def _clear_locked(self) -> None:
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

    def begin_orphan_shutdown(self) -> bool:
        """Commit shutdown only while an on-demand gateway still has no clients."""
        with self.transition_lock, self.lifecycle_lock, self.lock:
            state = self._live_state()
            if not bool(state.get("auto_stop")) or self._clients(state):
                self._write_or_clear(state)
                return False
            state["stopping"] = True
            self._write_state(state)
            return True

    def release(self, *, timeout_s: int = 20, wait_for_stop: bool = True) -> bool:
        """Release this client, optionally leaving last-client shutdown to the monitor."""
        if not self._acquired:
            return False
        while True:
            self.wait_for_shutdown()
            with self.transition_lock:
                with self.lifecycle_lock, self.lock:
                    state = self._live_state()
                    if state.get("stopping"):
                        continue
                    clients = self._clients(state)
                    clients.pop(self.token, None)
                    self._acquired = False
                    should_stop = not clients and bool(state.get("auto_stop"))
                    self._write_or_clear(state)
                if not should_stop or not wait_for_stop:
                    return False
                result = self.runtime._stop(timeout_s=timeout_s)
                stopped = result.ok or result.message in {
                    "gateway_not_running",
                    "gateway_state_stale",
                }
                with self.lifecycle_lock:
                    if stopped:
                        self._clear_locked()
                    else:
                        self._mark_ephemeral_locked()
                return stopped

    def wait_for_shutdown(self, *, timeout_s: float = 20) -> None:
        """Wait until a committed orphan shutdown can no longer accept clients."""
        deadline = time.monotonic() + timeout_s
        while True:
            with self.lifecycle_lock:
                with self.lock:
                    state = self._live_state()
                    if not state.get("stopping"):
                        return
                if not self.runtime.status().running:
                    self._finish_shutdown_locked()
                    return
            if time.monotonic() >= deadline:
                raise RuntimeError("gateway is still shutting down; try again shortly")
            time.sleep(0.05)

    def _shutdown_pending_locked(self) -> bool:
        with self.lock:
            return bool(self._live_state().get("stopping"))

    def _finish_shutdown_locked(self) -> None:
        with self.lock:
            state = self._live_state()
            state.pop("stopping", None)
            if not self._clients(state):
                self.state_path.unlink(missing_ok=True)
            else:
                self._write_state(state)

    def _register(self, state: dict[str, object]) -> None:
        clients = self._clients(state)
        record: dict[str, object] = {
            "pid": self.pid,
            "kind": self.kind,
        }
        record.update(process_identity_record(self._process_identity(self.pid), lease=True))
        clients[self.token] = record
        self._write_state(state)
        self._acquired = True

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
            identity = record.get("stable_identity")
            if identity is None:
                identity = record.get("identity")
            if not isinstance(pid, int) or not self._process_is_running(pid):
                stale.append(token)
                continue
            if self._process_identity_match(identity, pid) == "mismatch":
                stale.append(token)
        for token in stale:
            clients.pop(token, None)
        return state

    def _process_identity(self, pid: int) -> str | int | None:
        resolver = getattr(self.runtime, "process_identity", None)
        value = resolver(pid) if callable(resolver) else None
        return value if isinstance(value, (str, int)) else None

    def _process_identity_match(
        self,
        recorded: object,
        pid: int,
    ) -> Literal["match", "mismatch", "unknown"]:
        matcher = getattr(self.runtime, "process_identity_match", None)
        if callable(matcher):
            result = matcher(recorded, pid)
            if result in {"match", "mismatch", "unknown"}:
                return cast(Literal["match", "mismatch", "unknown"], result)
        if recorded is None:
            return "match"
        current = self._process_identity(pid)
        if current is None:
            return "unknown"
        return "match" if recorded == current else "mismatch"

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
            if lease.begin_orphan_shutdown():
                shutdown_event.set()
                return True
    return False


def _instance_suffix(*, workspace: str | None, config_path: str | None) -> str | None:
    raw = "|".join(value for value in (workspace, config_path) if value)
    if not raw:
        return None
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
