# Session storage

Conversation state is stored in `sessions.sqlite3` under
`<config-dir>/sessions/<workspace-id>/`, outside the agent workspace. The stable
workspace identity remains in `<workspace>/.nanobot/workspace-id`.

SQLite is the authoritative store for session metadata, ordered messages,
provider continuation state, pending inputs, and runtime checkpoints. Runtime
operations use a bounded worker queue and short transactions. Model requests,
tools, and network delivery run outside transactions. All connections enable
foreign keys and `synchronous=FULL`; the database uses WAL mode.

SDK session operations are asynchronous. Returned sessions are detached views
of committed state. Editing a returned snapshot does not save it. Import,
restore, reset, and deletion commit before returning. There is no `save=False`
mode or shutdown flush of mutable cached sessions.

The owner worker retains its SQLite connection until shutdown. Before reusing
cached history, it checks the session's revision and generation inside the
transaction. Committed message records remain private to the owner; each new
draft receives a detached history, while a commit copies only changed records
and writes the affected suffix. Metadata, follow-up, and checkpoint commands do
not read the message table. Conflicting history replacements still fail, and
failed transactions never publish a new cached view.

## JSONL migration window

| Milestone | Version |
| --- | --- |
| SQLite migration introduced | 0.3.6 |
| Final release line supporting JSONL migration | 0.4.x |
| Migration module and startup hook removed | **0.5.0** |

Stop the old gateway before upgrading. The first SQLite initialization imports
canonical JSONL files and legacy `<workspace>/sessions/*.jsonl` files, including
applicable checkpoint sidecars. The import and its completion marker commit in
one transaction. Original files remain unchanged. After the completion marker
exists, startup never scans JSONL sources again; deleting a migrated conversation
does not resurrect it from those files.

Malformed files or conflicting copies abort the entire import and report the
source path. Resolve the source data and restart; the failed import leaves no
partially imported conversations. Retain the original files until the imported
history has been checked.

Installations that still have only JSONL data must upgrade through a release in
the migration window before using 0.5.0. The version gate in
`tests/session/test_sqlite_storage.py` fails at 0.5.0 until the migration module,
its initialization hook, and migration-only tests are removed. Namespace identity
and JSONL export are independent of that retiring module.

## Export and backup

`nanobot sessions export-jsonl --config PATH --workspace PATH` exports conversation
copies into `<workspace>/sessions/`. Exported files are not a second live store;
editing them does not change SQLite state.

For a complete running-database backup, use SQLite's backup API or the SQLite
CLI's `.backup` command. Copying only `sessions.sqlite3` while the gateway is
running can omit committed records still held in its WAL file. WebUI display
transcripts and Memory files remain separate stores and must be included when
backing up the entire nanobot instance.
