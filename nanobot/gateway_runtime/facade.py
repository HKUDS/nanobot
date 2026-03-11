"""Runtime facade that hides platform policy and adapter selection."""

from __future__ import annotations

import ctypes
import os
from typing import Callable

from nanobot.gateway_runtime.adapters.base import RuntimeAdapter
from nanobot.gateway_runtime.adapters.foreground_legacy import ForegroundLegacyAdapter
from nanobot.gateway_runtime.adapters.linux_daemon import LinuxDaemonAdapter
from nanobot.gateway_runtime.adapters.posix_daemon import PosixDaemonAdapter
from nanobot.gateway_runtime.adapters.windows_daemon import WindowsDaemonAdapter
from nanobot.gateway_runtime.models import (
    GatewayStartOptions,
    GatewayStatus,
    RestartResult,
    RuntimeMode,
    RuntimePolicy,
    StartResult,
)
from nanobot.gateway_runtime.policy import resolve_runtime_policy
from nanobot.gateway_runtime.state_store import GatewayStateStore


class GatewayRuntimeFacade:
    """Gateway runtime command facade used by CLI entry points.

    Design goal: CLI semantics stay stable while runtime strategy can evolve.
    """

    def __init__(
        self,
        *,
        run_foreground_loop: Callable[[int, bool, str | None, str | None], None] | None = None,
        policy: RuntimePolicy | None = None,
        state_store: GatewayStateStore | None = None,
        adapter: RuntimeAdapter | None = None,
        prefer_recorded_mode: bool = False,
        preserve_live_legacy_restart_guard: bool = False,
    ):
        # policy/state_store/adapter are injectable for unit tests.
        # In normal runtime, defaults are resolved lazily from current env/platform.
        self._policy = policy or resolve_runtime_policy()
        self._state_store = state_store or GatewayStateStore()
        self._run_foreground_loop = run_foreground_loop
        self._prefer_recorded_mode = prefer_recorded_mode
        self._preserve_live_legacy_restart_guard = preserve_live_legacy_restart_guard
        self._adapter = adapter or self._build_adapter()

    def start(self, options: GatewayStartOptions) -> StartResult:
        """Start gateway using the selected adapter."""
        try:
            return self._adapter.start(options)
        except Exception:
            if not self._should_auto_fallback(options):
                raise
            fallback_policy = RuntimePolicy(
                mode=RuntimeMode.FOREGROUND_LEGACY,
                reason="fallback_to_legacy_foreground",
                platform=self._policy.platform,
                rollout_stage=self._policy.rollout_stage,
            )
            fallback_adapter = self._build_legacy_adapter(policy=fallback_policy)
            return fallback_adapter.start(options)

    def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
        """Restart gateway using adapter semantics for current runtime mode."""
        return self._adapter.restart(options, timeout_s=timeout_s)

    def status(self) -> GatewayStatus:
        """Return runtime status in a mode-agnostic shape."""
        return self._adapter.status()

    def logs(self, follow: bool = True, tail: int = 200) -> int:
        """Show logs through adapter-specific behavior."""
        return self._adapter.logs(follow=follow, tail=tail)

    def _build_adapter(self) -> RuntimeAdapter:
        """Select adapter by policy with platform-aware managed runtime support."""
        if self._policy.mode is RuntimeMode.FOREGROUND_LEGACY:
            return self._build_legacy_adapter(policy=self._policy)

        recorded_policy = self._resolve_recorded_policy_override()
        if recorded_policy is not None:
            return self._build_legacy_adapter(policy=recorded_policy)

        if self._policy.platform == "Darwin":
            return PosixDaemonAdapter(
                policy=self._policy,
                state_store=self._state_store,
            )

        if self._policy.platform == "Linux":
            return LinuxDaemonAdapter(
                policy=self._policy,
                state_store=self._state_store,
            )

        if self._policy.platform == "Windows":
            return WindowsDaemonAdapter(
                policy=self._policy,
                state_store=self._state_store,
            )

        fallback_policy = RuntimePolicy(
            mode=RuntimeMode.FOREGROUND_LEGACY,
            reason="fallback_to_legacy_foreground",
            platform=self._policy.platform,
            rollout_stage=self._policy.rollout_stage,
        )
        return self._build_legacy_adapter(policy=fallback_policy)


    def _resolve_recorded_policy_override(self) -> RuntimePolicy | None:
        if not self._prefer_recorded_mode:
            return None
        state = self._state_store.read_state() or {}
        recorded_mode = state.get("mode")
        if recorded_mode != RuntimeMode.FOREGROUND_LEGACY.value:
            return None
        if self._policy.reason.startswith("cli_override_"):
            if not self._preserve_live_legacy_restart_guard:
                return None
            pid = self._state_store.read_pid()
            if pid is None or not self._is_pid_running(pid):
                return None
        return RuntimePolicy(
            mode=RuntimeMode.FOREGROUND_LEGACY,
            reason=str(state.get("reason", self._policy.reason)),
            platform=str(state.get("platform", self._policy.platform)),
            rollout_stage=str(state.get("rollout_stage", self._policy.rollout_stage)),
        )

    def _is_pid_running(self, pid: int) -> bool:
        if self._policy.platform == "Windows":
            return self._is_pid_running_windows(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _is_pid_running_windows(self, pid: int) -> bool:
        process_query_limited_information = 0x1000
        still_active = 259

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_uint32()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    def _build_legacy_adapter(self, *, policy: RuntimePolicy) -> RuntimeAdapter:
        return ForegroundLegacyAdapter(
            run_foreground_loop=self._run_foreground_loop,
            policy=policy,
            state_store=self._state_store,
        )

    def _should_auto_fallback(self, options: GatewayStartOptions) -> bool:
        if self._policy.mode is not RuntimeMode.BACKGROUND_MANAGED:
            return False
        if self._policy.platform not in {"Darwin", "Linux", "Windows"}:
            return False
        # auto mode: no explicit CLI override; keep command resilient on default path.
        return options.cli_mode is None
