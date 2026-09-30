# Session storage

Conversation state is stored in `sessions.sqlite3` under
`<config-dir>/sessions/<workspace-id>/`, outside the agent workspace. The stable
workspace identity remains in `<workspace>/.nanobot/workspace-id`.

SQLite is the authoritative store for session metadata, ordered messages,
provider continuation state, pending inputs, and runtime checkpoints. Runtime
operations use a fixed-size worker pool, a bounded admission queue, per-session
FIFO ordering, and short transactions. Unrelated sessions can progress in
parallel; operations that inspect or change all sessions run as global barriers.
A full queue rejects the new operation instead of accumulating waiters. Model
requests, tools, and network delivery run outside transactions. All connections
enable foreign keys and `synchronous=FULL`; the database uses WAL mode.

SDK session operations are asynchronous. Returned sessions are detached views
of committed state. Editing a returned snapshot does not save it. Import,
restore, reset, and deletion commit before returning. There is no `save=False`
mode or shutdown flush of mutable cached sessions.

Each worker command opens and closes its own SQLite connection on that worker
thread. Before reusing cached history, the owner checks the session's revision
and generation inside the transaction. Committed message records remain private
to the owner; each new draft receives a detached history, while a commit copies
only changed records and writes the affected suffix. Metadata, follow-up, and
checkpoint commands do not read the message table. Conflicting history
replacements still fail, deleted generations reject late results, and failed
transactions never publish a new cached view.

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

Malformed files, duplicate JSON object keys, repeated provider-state records,
or duplicate session sources abort the entire import and report the source path.
Resolve the source data and restart; the failed import leaves no partially
imported conversations or completion marker. A marker value other than the exact
word `complete` also fails closed rather than skipping or repeating an uncertain
migration. Retain the original files until the imported history has been checked.

Installations that still have only JSONL data must upgrade through a release in
the migration window before using 0.5.0. The version gate in
`tests/session/test_sqlite_storage.py` fails at 0.5.0 until the migration module,
its initialization hook, and migration-only tests are removed. Namespace identity
and JSONL export are independent of that retiring module.

## Export and backup

`nanobot sessions export-jsonl --config PATH --workspace PATH` synchronizes a
complete portable snapshot into `<workspace>/sessions/`. A successful repeat
export replaces current session files and removes stale JSONL and checkpoint
sidecars, so a previously deleted session is not restored by a new database or
an older release. The directory is managed by this command, not an append-only
archive. Exported files are not a second live store; editing them does not change
SQLite state.

An export is sensitive and is not redacted. It contains full messages, metadata,
runtime checkpoints, pending inputs, and opaque provider continuation data,
which may include prompts, tool output, or secrets. The destination is inside the
agent-readable workspace and may also be visible to file tools, synchronization
software, or version control. Keep it private (`0700` directory and `0600` files
on Unix; restrictive ACLs on Windows), clean it up when no longer needed, and do
not publish it as a transcript. A fresh database or a pre-SQLite release can
import these files.

For an exact backup containing every accepted session command, stop the gateway
gracefully and let the owner drain first. For an online consistent snapshot of
already committed state, use SQLite's backup API or the SQLite CLI's `.backup`
command. Copying only `sessions.sqlite3` while the gateway is running can omit
committed records still held in its WAL file. Restore the database together with
`<workspace>/.nanobot/workspace-id`; that marker selects its session namespace.
JSONL export is a migration/portability format, not a complete instance backup.
WebUI display transcripts, Memory and history files, media, configuration, cron
and trigger definitions, and other runtime state remain separate and must be
backed up independently.
