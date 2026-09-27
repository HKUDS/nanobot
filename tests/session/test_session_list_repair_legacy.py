"""Completed migration makes legacy JSONL files inert."""

from nanobot.session.manager import SessionManager


def test_list_and_reads_ignore_files_created_after_migration(tmp_path):
    manager = SessionManager(tmp_path)
    (manager.sessions_dir / "cli_test.jsonl").write_text("invalid JSON")
    assert manager.list_sessions() == []
    assert manager.read_session_metadata("cli:test") is None
    assert manager.read_session_file("cli:test") is None
