import pytest

from nanobot.gateway_runtime.policy import RuntimeMode, resolve_runtime_policy


def test_darwin_rollout_defaults_to_background_managed() -> None:
    policy = resolve_runtime_policy(platform_name="Darwin")

    assert policy.mode is RuntimeMode.BACKGROUND_MANAGED
    assert policy.rollout_stage == "default_on"
    assert policy.platform == "Darwin"


@pytest.mark.parametrize("platform_name", ["Linux", "Windows"])
def test_linux_windows_rollout_defaults_to_foreground_legacy(platform_name: str) -> None:
    policy = resolve_runtime_policy(platform_name=platform_name)

    assert policy.mode is RuntimeMode.FOREGROUND_LEGACY
    assert policy.rollout_stage == "off"
    assert policy.platform == platform_name


def test_env_background_falls_back_to_legacy_when_rollout_is_off() -> None:
    policy = resolve_runtime_policy(
        platform_name="Linux",
        env={"NANOBOT_GATEWAY_MODE": "background"},
    )

    assert policy.mode is RuntimeMode.FOREGROUND_LEGACY
    assert policy.reason == "fallback_to_legacy_foreground"


def test_kill_switch_forces_foreground_when_cli_not_set() -> None:
    policy = resolve_runtime_policy(
        platform_name="Darwin",
        env={
            "NANOBOT_GATEWAY_MODE": "background",
            "NANOBOT_GATEWAY_KILL_SWITCH": "1",
        },
    )

    assert policy.mode is RuntimeMode.FOREGROUND_LEGACY
    assert policy.reason == "kill_switch_enabled"


def test_cli_mode_has_highest_priority_over_kill_switch_and_env() -> None:
    policy = resolve_runtime_policy(
        platform_name="Linux",
        cli_mode="background",
        env={
            "NANOBOT_GATEWAY_MODE": "foreground",
            "NANOBOT_GATEWAY_KILL_SWITCH": "1",
        },
    )

    assert policy.mode is RuntimeMode.FOREGROUND_LEGACY
    assert policy.reason == "fallback_to_legacy_foreground"


def test_cli_foreground_forces_legacy_mode() -> None:
    policy = resolve_runtime_policy(
        platform_name="Darwin",
        cli_mode="foreground",
        env={"NANOBOT_GATEWAY_MODE": "background"},
    )

    assert policy.mode is RuntimeMode.FOREGROUND_LEGACY
    assert policy.reason == "cli_override_foreground"


def test_empty_env_mapping_does_not_fallback_to_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_GATEWAY_MODE", "background")
    monkeypatch.setenv("NANOBOT_GATEWAY_KILL_SWITCH", "1")

    policy = resolve_runtime_policy(
        platform_name="Linux",
        env={},
    )

    assert policy.mode is RuntimeMode.FOREGROUND_LEGACY
    assert policy.reason == "rollout_off"
