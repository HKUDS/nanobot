# Session state ownership

`SessionState` owns runtime mutations. Its single worker executes accepted state
commands in order, with admission bounded to 32 operations. Callers receive
private drafts or detached committed views. Model calls, tools, event publication,
and network delivery happen outside storage transactions.

`SqliteSessionStore` owns SQLite transactions and the session schema. Messages,
checkpoints, and pending inputs have separate tables. Metadata commands do not
rewrite history. Checkpoint writes do not rewrite messages. A successful mutation
returns after its transaction commits with `synchronous=FULL`.

Turn commits apply their transcript changes to the latest committed session,
preserving unrelated metadata and later queued input. Reset assigns a new session
identity; late results and checkpoints from the old identity are rejected.
Administrative snapshots carry a revision so an obsolete save cannot replace
newer committed data.

Cancellation before admission submits no command. Cancellation after admission
waits for settlement. Closing the state owner rejects new commands and drains
accepted ones. It does not flush mutable cached objects. These guarantees cover
local persistence, not exactly-once external tool effects.

`SessionManager` supplies synchronous administrative reads and transactions for
CLI and HTTP worker code. AgentLoop, recovery, WebUI asynchronous flows, tools,
and the SDK use the asynchronous owner. Temporary conversations retain their
non-persistent policy and remain in memory.

JSONL import is isolated in `jsonl_migration.py`, introduced in 0.3.6 and scheduled
for removal in **0.5.0**. A durable completion marker prevents repeated import.
See [Session storage](../docs/session-storage.md) for migration and export rules.
