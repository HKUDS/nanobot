"""SQLite schema for nanobot auth (users, web sessions, audit log).

The auth DB lives at ``~/.nanobot/auth.db`` (or the equivalent under
``get_data_dir()``). Schema creation is idempotent. A file lock guards
init so concurrent gateway + CLI startups cannot race.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from filelock import FileLock
from loguru import logger

from nanobot.config.paths import get_data_dir

AUTH_DB_FILENAME = "auth.db"
_INIT_LOCK_FILENAME = ".auth-init.lock"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT,
    role            TEXT NOT NULL DEFAULT 'user',
    created_at      INTEGER NOT NULL,
    last_login_at   INTEGER,
    disabled        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,
    last_seen_at    INTEGER NOT NULL,
    user_agent      TEXT,
    ip              TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON web_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON web_sessions(expires_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              INTEGER NOT NULL,
    actor_user_id   TEXT,
    event           TEXT NOT NULL,
    target_user_id  TEXT,
    ip              TEXT,
    detail          TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


def get_auth_db_path(data_dir: Path | None = None) -> Path:
    """Resolve the on-disk path for the auth database."""
    base = data_dir if data_dir is not None else get_data_dir()
    return base / AUTH_DB_FILENAME


def open_auth_db(data_dir: Path | None = None) -> sqlite3.Connection:
    """Open a connection to the auth DB with sane pragmas.

    Callers own the connection lifecycle. Use ``init_auth_db`` once at
    process startup to materialize the schema.
    """
    path = get_auth_db_path(data_dir)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_auth_db(data_dir: Path | None = None) -> Path:
    """Create the auth DB and schema if absent. Idempotent and lock-guarded."""
    base = data_dir if data_dir is not None else get_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    db_path = get_auth_db_path(base)
    lock = FileLock(str(base / _INIT_LOCK_FILENAME))
    with lock:
        first = not db_path.exists()
        with open_auth_db(base) as conn:
            conn.executescript(_SCHEMA)
        if first:
            logger.info(f"Auth: initialized {db_path}")
        else:
            logger.debug(f"Auth: schema verified at {db_path}")
    return db_path
