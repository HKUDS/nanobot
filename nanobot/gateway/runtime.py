"""Gateway-specific configuration for the shared background process runtime."""

from __future__ import annotations

import hashlib
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


class GatewayRuntime(ManagedProcessRuntime):
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


def _instance_suffix(*, workspace: str | None, config_path: str | None) -> str | None:
    raw = "|".join(value for value in (workspace, config_path) if value)
    if not raw:
        return None
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
