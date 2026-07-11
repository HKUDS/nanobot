"""Background process control for the WebUI-managed OpenAI-compatible API."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from nanobot.gateway.runtime import (
    GatewayRuntime,
    GatewayRuntimePaths,
    GatewayStartOptions,
)


@dataclass(frozen=True)
class ApiStartOptions(GatewayStartOptions):
    """Options needed to start a managed ``nanobot serve`` process."""

    host: str = "127.0.0.1"


def api_runtime_paths(config_path: Path) -> GatewayRuntimePaths:
    """Return isolated state and log paths for one API process."""
    resolved = config_path.expanduser().resolve(strict=False)
    suffix = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    run_dir = resolved.parent / "run"
    logs_dir = resolved.parent / "logs"
    return GatewayRuntimePaths(
        run_dir=run_dir,
        logs_dir=logs_dir,
        state_path=run_dir / f"api.{suffix}.json",
        log_path=logs_dir / f"api.{suffix}.log",
    )


class ApiRuntime(GatewayRuntime):
    """Manage the API process without duplicating platform process handling."""

    def _build_child_command(self, options: ApiStartOptions) -> list[str]:
        command = [
            self.python_executable or sys.executable,
            "-m",
            "nanobot",
            "serve",
            "--host",
            options.host,
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

