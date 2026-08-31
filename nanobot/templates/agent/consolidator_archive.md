Create a complete replacement memory overview by consolidating the existing archived summary with the final {{ archive_count }} conversation messages immediately before this instruction.

When the system prompt contains `[Archived Context Summary]`, use it as the previous checkpoint and carry forward every still-relevant fact and working-state item. Treat the final {{ archive_count }} messages as the newly archived chunk and source new facts from them. Use earlier conversation messages to resolve references.

Apply corrections and newer decisions so the replacement overview reflects the current state. Produce a self-contained checkpoint with all facts and working-state details needed for future continuity.

Classify facts from the newly archived chunk with the SNIP criteria. Facts satisfying all four criteria receive their best matching memory mark; remaining candidates receive [skip].
- Signal: remembering it saves the user from repeating it
- Novel: adds distinct information within this conversation chunk
- Important: prevents rework or captures preferences / rules
- Persistent: still relevant after 2 weeks

Always preserve a compact working-state handoff: the active objective, current status, completed steps, unresolved blockers, next action, and exact identifiers needed for seamless continuation. Mark these facts [ephemeral].

Format each fact as:
- [mark] fact content

Marks (choose the best match):
- [permanent] Core preferences, personal traits, habits — relevant indefinitely
- [durable] Technical discoveries, project knowledge, config details — valid for months
- [ephemeral] Active task state, temporary decisions — may change in weeks
- [correction] Correction to a previous memory — state what changed
- [skip] Conversational filler, code/source facts derivable from the repo, or audit-only breadcrumbs

Priority: user corrections and preferences > solutions > decisions > events > environment facts.

Facts that also appear in long-term memory remain eligible for their best matching mark.

Return formatted fact lines, one per line. Represent an empty combined checkpoint as `(nothing)`.
