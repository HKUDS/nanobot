"""Background process control for the WebUI-managed OpenAI-compatible API."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from nanobot.process_runtime import (
    ManagedProcessRuntime,
    ProcessRuntimePaths,
    ProcessStartOptions,
)


@dataclass(frozen=True)
class ApiStartOptions(ProcessStartOptions):
    """Options needed to start a managed ``nanobot serve`` process."""

    host: str = "127.0.0.1"


def api_runtime_paths(config_path: Path) -> ProcessRuntimePaths:
    """Return isolated state and log paths for one API process."""
    resolved = config_path.expanduser().resolve(strict=False)
    suffix = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    run_dir = resolved.parent / "run"
    logs_dir = resolved.parent / "logs"
    return ProcessRuntimePaths(
        run_dir=run_dir,
        logs_dir=logs_dir,
        state_path=run_dir / f"api.{suffix}.json",
        log_path=logs_dir / f"api.{suffix}.log",
    )


class ApiRuntime(ManagedProcessRuntime):
    """Manage a WebUI-controlled OpenAI-compatible API process."""

    service_name = "api"

    def _build_child_command(self, options: ProcessStartOptions) -> list[str]:
        api_options = cast(ApiStartOptions, options)
        command = [
            self.python_executable or sys.executable,
            "-m",
            "nanobot",
            "serve",
            "--host",
            api_options.host,
            "--port",
            str(api_options.port),
        ]
        if api_options.verbose:
            command.append("--verbose")
        if api_options.workspace:
            command.extend(["--workspace", api_options.workspace])
        if api_options.config_path:
            command.extend(["--config", api_options.config_path])
        return command
