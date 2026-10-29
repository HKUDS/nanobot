"""Replace a cleaned-up gateway without invoking external stop/restart control.

The pure request/ticket API lives in ``nanobot.utils.restart`` so core execution
need not import a gateway adapter. This owner captures canonical gateway selectors,
never ``sys.argv`` (which can be a one-use protected update startup command).
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.gateway.runtime import (
    GatewayAlreadyRunningError,
    GatewayClientLease,
    GatewayLaunchMode,
    GatewayLifetime,
    GatewayRuntime,
    GatewayRuntimePaths,
    GatewayStartOptions,
    build_gateway_command,
)
from nanobot.utils.restart import RestartMode, replace_process, resolve_restart_mode
from nanobot.utils.rotating_output import (
    BACKGROUND_LOG_BACKUP_COUNT_ENV,
    BACKGROUND_LOG_MAX_BYTES_ENV,
    BACKGROUND_LOG_PATH_ENV,
    DEFAULT_BACKUP_COUNT,
    DEFAULT_MAX_BYTES,
)

_BACKGROUND_RESTART_ENV = "NANOBOT_GATEWAY_RESTART_BACKGROUND"
_UPDATE_STARTUP_TOKEN_ENV = "NANOBOT_UPDATE_STARTUP_TOKEN"


def claim_restarted_background(runtime: GatewayRuntime, options: GatewayStartOptions) -> None:
    """Consume an exec handoff before ordinary foreground claim initialization.

    The old gateway has already released its claim; exec has no managed spawn
    parent to publish a replacement. Seed only this matching instance's background
    identity so the existing claim path preserves its local-client lifetime.
    """
    selector = os.environ.pop(_BACKGROUND_RESTART_ENV, None)
    if selector != str(runtime.paths.state_path):
        return
    with runtime._transition_lock(), runtime._lifecycle_lock():
        current = runtime.status()
        if current.running:
            raise GatewayAlreadyRunningError(current)
        state: dict[str, object] = {
            "pid": os.getpid(),
            "launch_mode": "background",
            "port": options.port,
            "command": build_gateway_command(runtime.python_executable, options),
        }
        state.update(runtime.process_identity_record(os.getpid()))
        runtime._write_state(state)


@dataclass(frozen=True)
class GatewayRestartPlan:
    """Launch context captured while this process still owns the gateway claim."""

    options: GatewayStartOptions
    paths: GatewayRuntimePaths
    cwd: Path
    launch_mode: GatewayLaunchMode
    lifetime: GatewayLifetime
    mode: RestartMode

    def execute(self) -> None:
        """Called by the outer entrypoint after all old-owner leases unwind."""
        mode = resolve_restart_mode(self.mode)
        if mode == "exit":
            return
        environment = os.environ.copy()
        environment.pop(_UPDATE_STARTUP_TOKEN_ENV, None)
        environment.pop(_BACKGROUND_RESTART_ENV, None)
        argv = build_gateway_command(sys.executable, self.options)
        if self.launch_mode != "background":
            replace_process(argv, mode=mode, cwd=self.cwd, env=environment)
            return

        def spawn(command: list[str], **kwargs: Any) -> subprocess.Popen[str] | subprocess.Popen[bytes]:
            kwargs["env"] = {**environment, **kwargs["env"]}
            kwargs["env"].pop(_UPDATE_STARTUP_TOKEN_ENV, None)
            kwargs["env"].pop(_BACKGROUND_RESTART_ENV, None)
            return subprocess.Popen(command, cwd=self.cwd, **kwargs)

        runtime = GatewayRuntime(paths=self.paths, popen=spawn)
        with runtime._transition_lock(), runtime._lifecycle_lock():
            current = runtime.status()
            if current.running:
                raise GatewayAlreadyRunningError(current)
            # Normal release can remove the empty lease file. Preserve on-demand
            # intent; the new monitor may then stop if clients really disappeared.
            if self.lifetime == "on_demand":
                GatewayClientLease(runtime, kind="gateway-restart")._mark_ephemeral_locked()
            if mode == "spawn":
                # Unlike start_background/start_on_demand, this does not promote
                # the lifetime or stop/wait for our own, already released process.
                result = runtime._start_background(self.options)
                if not result.ok:
                    raise RuntimeError(f"Gateway replacement failed: {result.message}")
                return
        environment[_BACKGROUND_RESTART_ENV] = str(self.paths.state_path)
        environment[BACKGROUND_LOG_PATH_ENV] = str(self.paths.log_path)
        environment[BACKGROUND_LOG_MAX_BYTES_ENV] = str(DEFAULT_MAX_BYTES)
        environment[BACKGROUND_LOG_BACKUP_COUNT_ENV] = str(DEFAULT_BACKUP_COUNT)
        replace_process(argv, mode=mode, cwd=self.cwd, env=environment)
