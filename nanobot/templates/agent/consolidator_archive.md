Create a complete replacement memory overview from the existing archived summary and the final {{ archive_count }} conversation messages immediately before this instruction.

If the system prompt contains `[Archived Context Summary]`, treat it as the previous checkpoint. Preserve every still-relevant fact and working-state item from that checkpoint even when the new messages do not repeat it. The final {{ archive_count }} messages are the newly archived chunk. Any earlier conversation messages are context for resolving references, not a second source of new facts.

Merge corrections and newer decisions into the replacement overview instead of keeping stale versions. The returned overview must stand on its own: future requests will receive it without earlier `history.jsonl` entries.

Use [skip] unless a fact meets all SNIP criteria:
- Signal: would the user need to repeat this if forgotten?
- Novel: not just a restatement of another fact in this same conversation chunk
- Important: prevents rework or captures preferences / rules
- Persistent: still relevant after 2 weeks

Also preserve a compact working-state handoff even when it is not Persistent: the active objective, current status, completed steps, unresolved blockers, next action, and exact identifiers needed to continue without rework. Mark these facts [ephemeral].

Format each fact as:
- [mark] fact content

Marks (choose the best match):
- [permanent] Core preferences, personal traits, habits — never becomes stale
- [durable] Technical discoveries, project knowledge, config details — valid for months
- [ephemeral] Active task state, temporary decisions — may change in weeks
- [correction] Correction to a previous memory — state what changed
- [skip] Conversational filler, code/source facts derivable from the repo, or audit-only breadcrumbs

Priority: user corrections and preferences > solutions > decisions > events > environment facts.

Do not mark something [skip] merely because it might already exist in long-term memory.

Return only formatted fact lines. Return `(nothing)` only when there is no existing archived summary and the new chunk contains nothing noteworthy.
