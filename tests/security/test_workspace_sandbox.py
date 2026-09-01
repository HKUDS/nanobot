from pathlib import Path

from nanobot.security.workspace_access import workspace_sandbox_status


def test_workspace_sandbox_disabled(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=False,
        workspace=tmp_path,
        environ={},
    )

    assert status.level == "off"
    assert status.enforced is False
    assert status.provider == "none"
    assert status.as_dict()["workspace_root"] == str(tmp_path.resolve())


def test_workspace_sandbox_application_guard(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        environ={},
    )

    assert status.level == "application"
    assert status.enforced is False
    assert status.provider == "none"
    assert "application-level" in status.summary


def test_workspace_sandbox_system_provider_from_compact_env(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        environ={"NANOBOT_SANDBOX_ENFORCED": "macos_app_sandbox"},
    )

    assert status.level == "system"
    assert status.enforced is True
    assert status.provider == "macos_app_sandbox"
    assert status.provider_label == "macOS App Sandbox"


def test_workspace_sandbox_system_provider_from_boolean_env(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        environ={
            "NANOBOT_WORKSPACE_SANDBOX_ENFORCED": "true",
            "NANOBOT_WORKSPACE_SANDBOX_PROVIDER": "macOS App Sandbox",
        },
    )

    assert status.level == "system"
    assert status.enforced is True
    assert status.provider == "macos_app_sandbox"


def test_workspace_sandbox_false_env_does_not_enforce(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        environ={"NANOBOT_WORKSPACE_SANDBOX_ENFORCED": "false"},
    )

    assert status.level == "application"
    assert status.enforced is False
