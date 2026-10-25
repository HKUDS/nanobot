"""Durability configuration is applied to every SQLite connection."""

from nanobot.session.manager import SessionManager


def test_every_transaction_uses_full_synchronous_and_foreign_keys(tmp_path):
    manager = SessionManager(tmp_path)
    for _ in range(2):
        with manager._store.transaction() as db:
            assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
