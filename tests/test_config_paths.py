from pathlib import Path

from nanobot.config.schema import Config
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
)


def test_runtime_dirs_follow_workspace_root(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "instance-a" / "workspace"
    cfg = Config()
    cfg.agents.defaults.workspace = str(workspace)
    monkeypatch.setattr("nanobot.config.paths.load_config", lambda: cfg)

    assert get_data_dir() == workspace
    assert get_runtime_subdir("cron") == workspace / "cron"
    assert get_cron_dir() == workspace / "cron"
    assert get_logs_dir() == workspace / "logs"


def test_media_dir_supports_channel_namespace(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "instance-b" / "workspace"
    cfg = Config()
    cfg.agents.defaults.workspace = str(workspace)
    monkeypatch.setattr("nanobot.config.paths.load_config", lambda: cfg)

    assert get_media_dir() == workspace / "media"
    assert get_media_dir("telegram") == workspace / "media" / "telegram"


def test_shared_and_legacy_paths_remain_global() -> None:
    assert get_cli_history_path() == Path.home() / ".nanobot" / "history" / "cli_history"
    assert get_bridge_install_dir() == Path.home() / ".nanobot" / "bridge"
    assert get_legacy_sessions_dir() == Path.home() / ".nanobot" / "sessions"


def test_workspace_path_is_explicitly_resolved() -> None:
    cfg = Config()
    assert get_workspace_path(str(cfg.workspace_path)) == cfg.workspace_path
    assert get_workspace_path("~/custom-workspace") == Path.home() / "custom-workspace"
