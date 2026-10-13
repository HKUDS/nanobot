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

## Schema evolution

SQLite schema versions are independent of application release versions and the
JSONL migration window. Startup reads `PRAGMA user_version` and applies each
pending schema migration in order. Schema changes, version updates, and any
initial JSONL import commit in one transaction; a failure rolls them back so
startup can retry. An older binary rejects a database with a newer schema before
changing its journal mode or writing session data. Downgrading requires restoring
a backup compatible with the target release.

Session metadata and message records retain their JSON fields through storage
reads and writes. Add optional attributes there when they need no SQL index,
relationship, or constraint, and define defaults for older records. Fields that
need indexed queries or database constraints belong in columns or separate tables
with a schema migration. Changing a JSON field's name, type, or meaning needs a
record compatibility rule even when the SQL schema stays the same.

Schema migrations are appended to `_SCHEMA_MIGRATIONS` in
`nanobot/session/sqlite_store.py`; preserve previously released entries, including
the initial v1 schema. Migration functions use the supplied connection without
committing independently or calling `executescript`, which commits an existing
transaction. Add optional columns with nullable values or defaults so
existing rows and unchanged write paths remain valid. Every `INSERT` names its
columns explicitly.
Before releasing a migration, verify upgrading the previous schema preserves its
session state, reopening does not repeat the migration, and a failed upgrade
leaves the previous schema and data intact.

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
its initialization hook, and migration-only tests are removed. Workspace namespace
identity is independent of that retiring module.

## Backup

For an exact backup containing every accepted session command, stop the gateway
gracefully and let the owner drain first. For an online consistent snapshot of
already committed state, use SQLite's backup API or the SQLite CLI's `.backup`
command. Copying only `sessions.sqlite3` while the gateway is running can omit
committed records still held in its WAL file. Restore the database together with
`<workspace>/.nanobot/workspace-id`; that marker selects its session namespace.
WebUI display transcripts, Memory and history files, media, configuration, cron
and trigger definitions, and other runtime state remain separate and must be
backed up independently.
