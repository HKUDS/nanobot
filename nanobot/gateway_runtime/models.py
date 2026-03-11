"""Shared models for gateway runtime control plane."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class RuntimeMode(str, Enum):
    """Supported gateway runtime modes."""

    # Keep existing foreground behavior as compatibility baseline.
    FOREGROUND_LEGACY = "foreground_legacy"
    # Reserved for managed daemon/service adapters.
    BACKGROUND_MANAGED = "background_managed"


@dataclass(frozen=True)
class RuntimePolicy:
    """Resolved runtime policy for the current command execution.

    mode: effective runtime mode after applying CLI/env/rollout rules.
    reason: machine-friendly explanation for the decision (for status/debug).
    platform: platform used for rollout gating (Darwin/Linux/Windows).
    rollout_stage: rollout state for the platform (off/opt_in/default_on).
    """

    mode: RuntimeMode
    reason: str
    platform: str
    rollout_stage: str


# Flexible JSON-like payload persisted to gateway.state.json.
GatewayRuntimeState = dict[str, Any]


@dataclass(frozen=True)
class GatewayStartOptions:
    """Gateway start options shared between CLI and adapters.

    cli_mode preserves the raw CLI intent ("foreground"/"background"), which
    helps with status/debug output even when policy later falls back.
    """

    port: int = 18790
    verbose: bool = False
    # Optional instance selectors for config/workspace aware runtime wiring.
    workspace: str | None = None
    config_path: str | None = None
    cli_mode: str | None = None


@dataclass(frozen=True)
class StartResult:
    """Result from runtime start operation.

    message is a stable machine-readable status string for CLI output.
    """

    started: bool
    message: str
    mode: RuntimeMode


@dataclass(frozen=True)
class RestartResult:
    """Result from runtime restart operation.

    In framework phase this can be a non-destructive compatibility response.
    """

    restarted: bool
    message: str
    mode: RuntimeMode


@dataclass(frozen=True)
class StopResult:
    """Result from runtime stop operation."""

    stopped: bool
    message: str
    mode: RuntimeMode


@dataclass(frozen=True)
class GatewayStatus:
    """Status payload exposed by runtime facade and adapters.

    pid/log_path are optional because legacy mode may not manage a process.
    """

    running: bool
    mode: RuntimeMode
    reason: str
    platform: str
    rollout_stage: str
    pid: int | None = None
    pgid: int | None = None
    log_path: Path | None = None
    started_at: str | None = None
