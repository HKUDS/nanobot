"""Legacy foreground runtime adapter (single source of truth path)."""

from __future__ import annotations

from typing import Callable

import typer

from nanobot.gateway_runtime.models import (
    GatewayStartOptions,
    GatewayStatus,
    RestartResult,
    RuntimeMode,
    RuntimePolicy,
    StartResult,
    StopResult,
)
from nanobot.gateway_runtime.state_store import GatewayStateStore


class ForegroundLegacyAdapter:
    """Adapter that delegates gateway execution to the existing foreground loop.

    This adapter intentionally keeps old behavior:
    - start: run foreground loop directly
    - restart/stop: non-destructive compatibility responses
    - status/logs: explain legacy mode instead of failing command
    """

    def __init__(
        self,
        *,
        run_foreground_loop: Callable[[int, bool, str | None, str | None], None] | None,
        policy: RuntimePolicy,
        state_store: GatewayStateStore | None = None,
    ):
        self._run_foreground_loop = run_foreground_loop
        self._policy = policy
        self._state_store = state_store or GatewayStateStore()

    def start(self, options: GatewayStartOptions) -> StartResult:
        # Adapter can be created for read-only commands where a runner is not needed.
        if self._run_foreground_loop is None:
            return StartResult(
                started=False,
                message="legacy_foreground_runner_not_available",
                mode=RuntimeMode.FOREGROUND_LEGACY,
            )

        # Persist lightweight runtime metadata for status/debug observability.
        self._state_store.write_state(
            {
                "mode": RuntimeMode.FOREGROUND_LEGACY.value,
                "reason": self._policy.reason,
                "platform": self._policy.platform,
                "rollout_stage": self._policy.rollout_stage,
            }
        )
        self._run_foreground_loop(
            options.port,
            options.verbose,
            options.workspace,
            options.config_path,
        )
        return StartResult(
            started=True,
            message="gateway_started_foreground_legacy",
            mode=RuntimeMode.FOREGROUND_LEGACY,
        )

    def stop(self, timeout_s: int = 20) -> StopResult:
        # Legacy mode has no managed background process to signal.
        return StopResult(
            stopped=False,
            message="legacy_foreground_has_no_managed_process_to_stop",
            mode=RuntimeMode.FOREGROUND_LEGACY,
        )

    def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
        # Framework phase keeps restart non-destructive for legacy compatibility.
        return RestartResult(
            restarted=False,
            message="legacy_foreground_requires_manual_restart",
            mode=RuntimeMode.FOREGROUND_LEGACY,
        )

    def status(self) -> GatewayStatus:
        pid = self._state_store.read_pid()
        # In legacy mode, running is best-effort from pid file only.
        # Process-level verification is a later enhancement.
        return GatewayStatus(
            running=pid is not None,
            mode=RuntimeMode.FOREGROUND_LEGACY,
            reason=self._policy.reason,
            platform=self._policy.platform,
            rollout_stage=self._policy.rollout_stage,
            pid=pid,
            log_path=self._state_store.resolve_log_path(),
        )

    def logs(self, follow: bool = True, tail: int = 200) -> int:
        # Keep logs command available even when no daemon log stream exists.
        typer.echo(
            "Gateway is in foreground mode; no managed background log stream is available."
        )
        return 0
