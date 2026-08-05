"""Background process control for the WebUI-managed OpenAI-compatible API."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

from nanobot.process_runtime import (
    ManagedProcessRuntime,
    ProcessRuntimePaths,
    ProcessStartOptions,
    ProcessStatus,
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


def probe_api_health(host: str, port: int, *, timeout: float = 0.5) -> bool:
    """Return True when a nanobot API answers on ``host:port``.

    The API server exposes an unauthenticated ``/health`` endpoint that
    identifies itself with a ``service`` field; a matching response means a
    ``nanobot serve`` instance is already listening, even when this gateway
    did not start it (for example, a systemd-managed service).
    """
    url = f"http://{host}:{port}/health"
    try:
        with urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("service") == "nanobot"
    except (OSError, ValueError):
        return False


class ApiRuntime(ManagedProcessRuntime[ApiStartOptions]):
    """Manage a WebUI-controlled OpenAI-compatible API process."""

    service_name = "api"

    def effective_status(
        self,
        *,
        host: str,
        port: int,
        probe_timeout: float = 0.5,
    ) -> ProcessStatus:
        """Return live status, including externally-managed API servers.

        When no process is recorded in this runtime's state file, probe the
        configured endpoint: an API answering on ``/health`` was started
        outside this gateway (e.g. systemd) and is reported as running with
        ``managed=False`` so callers never treat it as their own.

        Detection is scoped to the endpoint given here. An API instance
        started from a different config file is inspected separately, e.g.
        via ``nanobot api status --config <path>``.
        """
        status = self.status()
        if status.running:
            return status
        if probe_api_health(host, port, timeout=probe_timeout):
            return ProcessStatus(
                running=True,
                pid=None,
                state_path=self.paths.state_path,
                log_path=self.paths.log_path,
                port=port,
                reason="external",
            )
        return status

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
