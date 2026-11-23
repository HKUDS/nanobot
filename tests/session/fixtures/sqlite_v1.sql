CREATE TABLE storage_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sessions (
    key TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL, provider_state TEXT, last_archived INTEGER NOT NULL,
    revision INTEGER NOT NULL, generation TEXT NOT NULL,
    title TEXT NOT NULL, preview TEXT NOT NULL, visible_updated_at TEXT
);
CREATE TABLE messages (
    session_key TEXT NOT NULL REFERENCES sessions(key) ON DELETE CASCADE,
    position INTEGER NOT NULL, record TEXT NOT NULL,
    PRIMARY KEY (session_key, position)
);
CREATE TABLE checkpoints (
    session_key TEXT PRIMARY KEY REFERENCES sessions(key) ON DELETE CASCADE,
    record TEXT NOT NULL
);
CREATE TABLE pending_inputs (
    session_key TEXT NOT NULL REFERENCES sessions(key) ON DELETE CASCADE,
    kind TEXT NOT NULL, position INTEGER NOT NULL, record TEXT NOT NULL,
    PRIMARY KEY (session_key, kind, position)
);
CREATE INDEX sessions_updated ON sessions(updated_at DESC);
INSERT INTO storage_meta (key, value) VALUES ('jsonl_import', 'complete');
PRAGMA user_version = 1;
