from pathlib import Path

from typer.testing import CliRunner

from nanobot.cli import commands
from nanobot.config.loader import load_config
from nanobot.session.manager import SessionManager


def test_sessions_export_jsonl_command_writes_portable_snapshot(
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
    manager.save(session)
    monkeypatch.setattr(commands, "_load_runtime_config", lambda *_args: config)

    result = CliRunner().invoke(commands.app, ["sessions", "export-jsonl"])

    assert result.exit_code == 0, result.output
    assert "Exported 1 session(s)" in result.output
    restored = workspace / "sessions" / f"{manager._storage_key(session.key)}.jsonl"
    assert restored.exists()
    assert "restore-me" in restored.read_text(encoding="utf-8")
    assert manager.read_session_snapshot(session.key) is not None
