# Tool checkpoint compatibility rollout

This change is the **reader-first** prerequisite for partial tool-batch checkpoints
(#5747), not the completion of that feature. Tool execution and checkpoint writers
are unchanged: `awaiting_tools` still records all calls as pending, and
`tools_completed` records all results after execution finishes.

The recovery reader additionally accepts `awaiting_tools` records containing both
completed results and pending calls. Their IDs must be unique, disjoint, and cover
exactly the assistant's tool calls. Invalid partitions remain non-continuable.
Recovery preserves completed results, marks pending calls interrupted, discards
unsynchronized provider state, and waits for explicit user confirmation. It never
replays a tool automatically. Repeated startup does not duplicate restored rows.

## Release order

1. Ship this reader while retaining the existing writer. It creates no new
   checkpoint shape, so rollback to a preceding release remains possible.
2. In a separate release, enable awaited checkpoints after each execution batch.
   Set the minimum rollback version to a released version containing this reader.
   Keep the completed/pending partition and exactly-once normalization tests with
   that writer change. Parallel tools in one batch remain a single checkpoint unit.
3. Before rolling a writer-enabled installation back **below** that minimum,
   resolve its pending checkpoints using a reader-capable version and back up the
   session data. Older readers reject mixed checkpoints and can discard completed
   results; preserving the file format alone does not make that rollback safe.

No session locations, metadata ownership, display transcript stores, or discovery
indexes move. This rollout does not promise exactly-once external side effects or
durability for a tool result before its batch checkpoint is saved.
