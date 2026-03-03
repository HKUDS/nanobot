"""Runtime adapter contract for gateway execution backends.

The CLI should never branch on platform-specific runtime details directly.
It talks to GatewayRuntimeFacade, which delegates to one RuntimeAdapter.
"""

from typing import Protocol

from nanobot.gateway_runtime.models import (
    GatewayStartOptions,
    GatewayStatus,
    RestartResult,
    StartResult,
    StopResult,
)


class RuntimeAdapter(Protocol):
    """Adapter protocol for gateway runtime operations.

    All adapters expose the same command semantics:
    - start/restart/stop return structured results (not print directly).
    - status returns an always-available, explainable snapshot.
    - logs keeps command available even if mode has no daemon log stream.
    """

    def start(self, options: GatewayStartOptions) -> StartResult:
        """Start gateway runtime."""

    def stop(self, timeout_s: int = 20) -> StopResult:
        """Stop gateway runtime."""

    def restart(self, options: GatewayStartOptions, timeout_s: int = 20) -> RestartResult:
        """Restart gateway runtime."""

    def status(self) -> GatewayStatus:
        """Get gateway runtime status."""

    def logs(self, follow: bool = True, tail: int = 200) -> int:
        """Show runtime logs."""
