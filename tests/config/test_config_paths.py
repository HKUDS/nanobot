from pathlib import Path

import pytest

from nanobot.config.paths import (
    get_bridge_install_dir,
    get_cli_history_path,
    get_cron_dir,
    get_data_dir,
    get_legacy_sessions_dir,
    get_logs_dir,
    get_media_dir,
    get_runtime_subdir,
    get_workspace_path,
    is_default_workspace,
    set_workspace,
)


@pytest.fixture(autouse=True)
def _clear_workspace_pin():
    """Clear any in-process workspace pin so tests don't leak into each other."""
    set_workspace(None)
    yield
    set_workspace(None)


def test_runtime_dirs_follow_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "instance-a"
    set_workspace(workspace)

    data_dir = workspace / ".nanobot"
    assert get_data_dir() == data_dir
    assert get_runtime_subdir("cron") == data_dir / "cron"
    assert get_cron_dir() == data_dir / "cron"
    assert get_logs_dir() == data_dir / "logs"


def test_media_dir_supports_channel_namespace(tmp_path: Path) -> None:
    workspace = tmp_path / "instance-b"
    set_workspace(workspace)

    data_dir = workspace / ".nanobot"
    assert get_media_dir() == data_dir / "media"
    assert get_media_dir("telegram") == data_dir / "media" / "telegram"


def test_workspace_relative_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "instance-c"
    set_workspace(workspace)

    data_dir = workspace / ".nanobot"
    assert get_cli_history_path() == data_dir / "history" / "cli_history"
    assert get_bridge_install_dir() == data_dir / "bridge"
    # Legacy sessions dir is intentionally global — used only for migration.
    assert get_legacy_sessions_dir() == Path.home() / ".nanobot" / "sessions"


def test_workspace_path_defaults_to_home() -> None:
    assert get_workspace_path() == Path.home()
    assert get_workspace_path("~/custom-workspace") == Path.home() / "custom-workspace"


def test_is_default_workspace_distinguishes_default_and_custom_paths() -> None:
    assert is_default_workspace(None) is True
    assert is_default_workspace(Path.home()) is True
    assert is_default_workspace("~/custom-workspace") is False
