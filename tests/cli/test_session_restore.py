from pathlib import Path

from typer.testing import CliRunner

from nanobot.cli import commands
from nanobot.config.loader import load_config
from nanobot.session.manager import SessionManager


def test_sessions_restore_workspace_command_prepares_downgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    config_path = tmp_path / "instance" / "config.json"
    config = load_config(config_path)
    config.agents.defaults.workspace = str(workspace)
    manager = SessionManager(workspace, sessions_root=config_path.parent / "sessions")
    session = manager.get_or_create("cli:rollback")
    session.add_message("user", "restore-me")
    manager.save(session, fsync=True)
    monkeypatch.setattr(commands, "_load_runtime_config", lambda *_args: config)

    result = CliRunner().invoke(commands.app, ["sessions", "restore-workspace"])

    assert result.exit_code == 0, result.output
    assert "Restored 1 session file(s)" in result.output
    restored = workspace / "sessions" / manager._get_session_path(session.key).name
    assert restored.exists()
    assert "restore-me" in restored.read_text(encoding="utf-8")
    assert manager._get_session_path(session.key).exists()
