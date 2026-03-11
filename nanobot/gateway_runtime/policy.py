"""Runtime policy gate for cross-platform gateway behavior."""

import os
import platform
from typing import Mapping

from nanobot.gateway_runtime.models import RuntimeMode, RuntimePolicy

MODE_ENV_KEY = "NANOBOT_GATEWAY_MODE"
KILL_SWITCH_ENV_KEY = "NANOBOT_GATEWAY_KILL_SWITCH"

# Framework phase: keep all platforms in legacy foreground mode.
ROLLOUT_BY_PLATFORM: dict[str, str] = {
    "Darwin": "default_on",
    "Linux": "default_on",
    "Windows": "default_on",
}

_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_FOREGROUND_ALIASES = {"foreground", "legacy", "foreground_legacy"}
_BACKGROUND_ALIASES = {"background", "managed", "background_managed"}


def resolve_runtime_policy(
    *,
    cli_mode: str | None = None,
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> RuntimePolicy:
    """Resolve runtime policy with precedence: CLI > kill switch > env > rollout."""
    env_map = os.environ if env is None else env
    target_platform = platform_name or platform.system()
    rollout_stage = ROLLOUT_BY_PLATFORM.get(target_platform, "off")

    # 1) Explicit CLI flags always win.
    normalized_cli_mode = _normalize_mode(cli_mode)
    if normalized_cli_mode is not None:
        return _policy_from_mode(
            requested_mode=normalized_cli_mode,
            platform_name=target_platform,
            rollout_stage=rollout_stage,
            reason_for_foreground="cli_override_foreground",
            reason_for_background="cli_override_background",
        )

    # 2) Kill switch is a hard safety override for emergency rollback.
    if _is_kill_switch_enabled(env_map.get(KILL_SWITCH_ENV_KEY)):
        return RuntimePolicy(
            mode=RuntimeMode.FOREGROUND_LEGACY,
            reason="kill_switch_enabled",
            platform=target_platform,
            rollout_stage=rollout_stage,
        )

    # 3) Environment variable acts as a deployment-time hint.
    normalized_env_mode = _normalize_mode(env_map.get(MODE_ENV_KEY))
    if normalized_env_mode is not None:
        return _policy_from_mode(
            requested_mode=normalized_env_mode,
            platform_name=target_platform,
            rollout_stage=rollout_stage,
            reason_for_foreground="env_override_foreground",
            reason_for_background="env_override_background",
        )

    # 4) Finally, fall back to rollout defaults for current platform.
    if rollout_stage == "default_on":
        return RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason="rollout_default_on",
            platform=target_platform,
            rollout_stage=rollout_stage,
        )

    return RuntimePolicy(
        mode=RuntimeMode.FOREGROUND_LEGACY,
        reason="rollout_off",
        platform=target_platform,
        rollout_stage=rollout_stage,
    )


def _policy_from_mode(
    *,
    requested_mode: RuntimeMode,
    platform_name: str,
    rollout_stage: str,
    reason_for_foreground: str,
    reason_for_background: str,
) -> RuntimePolicy:
    """Translate a requested mode into an effective mode for this rollout stage."""
    if requested_mode is RuntimeMode.FOREGROUND_LEGACY:
        return RuntimePolicy(
            mode=RuntimeMode.FOREGROUND_LEGACY,
            reason=reason_for_foreground,
            platform=platform_name,
            rollout_stage=rollout_stage,
        )

    # Background is only effective for enabled rollout stages.
    if rollout_stage in {"opt_in", "default_on"}:
        return RuntimePolicy(
            mode=RuntimeMode.BACKGROUND_MANAGED,
            reason=reason_for_background,
            platform=platform_name,
            rollout_stage=rollout_stage,
        )

    return RuntimePolicy(
        mode=RuntimeMode.FOREGROUND_LEGACY,
        reason="fallback_to_legacy_foreground",
        platform=platform_name,
        rollout_stage=rollout_stage,
    )


def _normalize_mode(raw_mode: str | None) -> RuntimeMode | None:
    """Map raw CLI/env values to RuntimeMode, ignoring unknown values."""
    if raw_mode is None:
        return None
    normalized = raw_mode.strip().lower()
    if normalized in _FOREGROUND_ALIASES:
        return RuntimeMode.FOREGROUND_LEGACY
    if normalized in _BACKGROUND_ALIASES:
        return RuntimeMode.BACKGROUND_MANAGED
    return None


def _is_kill_switch_enabled(raw_value: str | None) -> bool:
    """Interpret common truthy values for kill switch env var."""
    if raw_value is None:
        return False
    return raw_value.strip().lower() in _TRUTHY_VALUES


__all__ = [
    "RuntimeMode",
    "RuntimePolicy",
    "resolve_runtime_policy",
]
